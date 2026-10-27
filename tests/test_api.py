"""HTTP integration tests with isolated databases and synthetic documents."""

from contextlib import closing
import hashlib
from io import BytesIO
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter

from spending.api import create_app
from spending.database import connect


def image_bytes(format_name='PNG', color='white'):
    output = BytesIO()
    Image.new('RGB', (12, 20), color).save(output, format=format_name)
    return output.getvalue()


def pdf_bytes(encrypted=False, empty=False):
    writer = PdfWriter()
    if not empty:
        writer.add_blank_page(width=200, height=300)
    if encrypted:
        writer.encrypt('test-password')
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class ReceiptAPITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.database_path = self.root / 'api.db'
        self.upload_dir = self.root / 'uploads'
        self.app = create_app(self.database_path, self.upload_dir)
        self.client = self.enterContext(TestClient(self.app))

    def upload(self, data=None, filename='receipt.png', content_type='image/png', client=None):
        return (client or self.client).post('/receipts', files={
            'file': (filename, image_bytes() if data is None else data, content_type),
        })

    def assert_no_uploads(self):
        with closing(connect(self.database_path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM Receipt').fetchone()[0], 0)
        self.assertEqual(list(self.upload_dir.iterdir()), [])

    def test_startup_and_health(self):
        self.assertTrue(self.database_path.exists())
        self.assertTrue(self.upload_dir.is_dir())
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok', 'database': 'ok'})

    def test_desktop_development_origin_is_allowed(self):
        response = self.client.options('/receipts', headers={
            'Origin': 'http://127.0.0.1:5173',
            'Access-Control-Request-Method': 'POST',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['access-control-allow-origin'], 'http://127.0.0.1:5173')

    def test_factory_defers_filesystem_changes_until_startup(self):
        root = self.root / 'not-started'
        create_app(root / 'db.sqlite', root / 'uploads')
        self.assertFalse(root.exists())
        with self.assertRaises(ValueError):
            create_app(max_upload_bytes=0)

    def test_upload_persists_original_bytes_hash_and_pending_record(self):
        data = image_bytes()
        response = self.upload(data, filename='../../receipt.png')
        self.assertEqual(response.status_code, 201)
        receipt = response.json()
        self.assertEqual(response.headers['location'], f"/receipts/{receipt['id']}")
        self.assertEqual(receipt['status'], 'pending')
        self.assertEqual(receipt['source_type'], 'upload')
        self.assertEqual(receipt['file_sha256'], hashlib.sha256(data).hexdigest())
        self.assertIsNone(receipt['purchase_date'])
        self.assertIsNone(receipt['total_pence'])
        key = receipt['source_path']
        self.assertEqual(Path(key).name, key)
        self.assertNotIn('receipt', key)
        self.assertEqual((self.upload_dir / key).read_bytes(), data)
        with closing(connect(self.database_path)) as db:
            self.assertEqual(db.execute('SELECT file_sha256 FROM Receipt').fetchone()[0], receipt['file_sha256'])
            self.assertEqual(db.execute('SELECT count(*) FROM ocr_runs').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM v_monthly_spending').fetchone()[0], 0)

    def test_accepts_png_jpeg_and_pdf(self):
        cases = [
            ('receipt.PNG', image_bytes(), 'image/png', '.png'),
            ('receipt.jpeg', image_bytes('JPEG'), 'image/jpeg', '.jpg'),
            ('receipt.pdf', pdf_bytes(), 'application/pdf', '.pdf'),
        ]
        for name, data, mime, suffix in cases:
            with self.subTest(name=name):
                response = self.upload(data, name, mime)
                self.assertEqual(response.status_code, 201, response.text)
                self.assertTrue(response.json()['source_path'].endswith(suffix))

    def test_generic_binary_mime_is_validated_by_contents(self):
        self.assertEqual(self.upload(content_type='application/octet-stream').status_code, 201)

    def test_duplicate_bytes_rejected_even_with_different_filename(self):
        first = self.upload().json()
        duplicate = self.upload(filename='different.PNG')
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()['detail']['receipt_id'], first['id'])
        self.assertEqual(len(list(self.upload_dir.iterdir())), 1)
        self.assertEqual(self.client.get('/receipts').json()['total'], 1)

    def test_delete_receipt_removes_file_and_derived_records(self):
        receipt = self.upload().json()
        with closing(connect(self.database_path)) as db, db:
            supermarket_id = db.execute("INSERT INTO Supermarket(name, location) VALUES ('Tesco', 'Example Extra')").lastrowid
            db.execute('UPDATE Receipt SET supermarket_id=? WHERE id=?', (supermarket_id, receipt['id']))
            item_id = db.execute(
                "INSERT INTO ReceiptItem(receipt_id, line_number, raw_description, original_pence) VALUES (?, 1, 'Milk', 120)",
                (receipt['id'],),
            ).lastrowid
            run_id = db.execute(
                "INSERT INTO ocr_runs(receipt_id, engine, status) VALUES (?, 'test', 'succeeded')", (receipt['id'],),
            ).lastrowid
            db.execute(
                "INSERT INTO correction_audit(receipt_id, receipt_item_id, ocr_run_id, field_name) VALUES (?, ?, ?, 'total_pence')",
                (receipt['id'], item_id, run_id),
            )
        response = self.client.delete(f"/receipts/{receipt['id']}")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(list(self.upload_dir.iterdir()), [])
        self.assertEqual(self.client.get(f"/receipts/{receipt['id']}").status_code, 404)
        with closing(connect(self.database_path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM Receipt').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM ReceiptItem').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM ocr_runs').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM correction_audit').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM Supermarket').fetchone()[0], 0)

    def test_processing_receipt_cannot_be_deleted(self):
        receipt = self.upload().json()
        with closing(connect(self.database_path)) as db, db:
            db.execute("UPDATE Receipt SET status='processing' WHERE id=?", (receipt['id'],))
        response = self.client.delete(f"/receipts/{receipt['id']}")
        self.assertEqual(response.status_code, 409)
        self.assertTrue((self.upload_dir / receipt['source_path']).is_file())

    def test_rejects_unsupported_extensions_and_mime_mismatch(self):
        for name, mime in [('receipt.txt', 'text/plain'), ('receipt.png', 'application/pdf')]:
            with self.subTest(name=name, mime=mime):
                self.assertEqual(self.upload(filename=name, content_type=mime).status_code, 415)
                self.assert_no_uploads()

    def test_rejects_corrupt_or_mislabeled_documents(self):
        cases = [
            ('receipt.png', b'<html>not an image</html>', 'image/png'),
            ('receipt.jpg', image_bytes(), 'image/jpeg'),
            ('receipt.png', image_bytes()[:32], 'image/png'),
            ('receipt.pdf', b'%PDF-1.7\ninvalid', 'application/pdf'),
            ('receipt.pdf', b'not pdf', 'application/pdf'),
            ('receipt.pdf', pdf_bytes(encrypted=True), 'application/pdf'),
            ('receipt.pdf', pdf_bytes(empty=True), 'application/pdf'),
        ]
        for name, data, mime in cases:
            with self.subTest(name=name, size=len(data)):
                self.assertEqual(self.upload(data, name, mime).status_code, 422)
                self.assert_no_uploads()

    def test_empty_and_missing_file_rejected(self):
        self.assertEqual(self.upload(b'').status_code, 422)
        self.assertEqual(self.client.post('/receipts').status_code, 422)
        self.assert_no_uploads()

    def test_size_limit_accepts_boundary_and_cleans_oversized_upload(self):
        data = image_bytes()
        limited = create_app(self.database_path, self.upload_dir, max_upload_bytes=len(data))
        with TestClient(limited) as client:
            self.assertEqual(self.upload(data + b'X', client=client).status_code, 413)
            self.assert_no_uploads()
            self.assertEqual(self.upload(data, client=client).status_code, 201)

    def test_empty_list_and_missing_receipt(self):
        self.assertEqual(self.client.get('/receipts').json(), {
            'items': [], 'total': 0, 'limit': 20, 'offset': 0,
        })
        self.assertEqual(self.client.get('/receipts/999').status_code, 404)

    def test_list_pagination_and_status_filter(self):
        with closing(connect(self.database_path)) as db, db:
            for status in ('pending', 'failed', 'pending', 'needs_review'):
                db.execute('INSERT INTO Receipt(status) VALUES (?)', (status,))
        page = self.client.get('/receipts?limit=2&offset=1').json()
        self.assertEqual(page['total'], 4)
        self.assertEqual([item['id'] for item in page['items']], [3, 2])
        pending = self.client.get('/receipts?status=pending').json()
        self.assertEqual(pending['total'], 2)
        self.assertEqual([item['id'] for item in pending['items']], [3, 1])
        self.assertEqual(self.client.get('/receipts?offset=100').json()['items'], [])

    def test_detail_returns_only_matching_receipt_items_in_line_order(self):
        receipt_id = self.upload().json()['id']
        with closing(connect(self.database_path)) as db, db:
            db.execute("INSERT INTO Receipt(id, status) VALUES (999, 'pending')")
            for parent, line, description in [(receipt_id, 2, 'Milk'), (999, 1, 'Other'), (receipt_id, 1, 'Rice')]:
                db.execute(
                    'INSERT INTO ReceiptItem(receipt_id, line_number, raw_description, original_pence) VALUES (?, ?, ?, 100)',
                    (parent, line, description),
                )
        detail = self.client.get(f'/receipts/{receipt_id}')
        self.assertEqual(detail.status_code, 200)
        self.assertEqual([item['raw_description'] for item in detail.json()['items']], ['Rice', 'Milk'])

    def test_invalid_pagination_status_and_ids_rejected(self):
        for url in ['/receipts?limit=0', '/receipts?limit=101', '/receipts?offset=-1',
                    '/receipts?status=unknown', '/receipts/0', '/receipts/abc']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 422)

    def test_database_upload_failure_removes_staged_file(self):
        with patch('spending.api.connect', side_effect=sqlite3.OperationalError('test failure')):
            with self.assertLogs('spending.api', level='ERROR'):
                response = self.upload()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('test failure', response.text)
        self.assert_no_uploads()

    def test_file_save_failure_rolls_back_receipt(self):
        with patch('spending.api.Path.replace', side_effect=OSError('test failure')):
            with self.assertLogs('spending.api', level='ERROR'):
                response = self.upload()
        self.assertEqual(response.status_code, 503)
        self.assert_no_uploads()

    def test_restart_preserves_receipts_and_duplicate_detection(self):
        receipt = self.upload().json()
        restarted = create_app(self.database_path, self.upload_dir)
        with TestClient(restarted) as client:
            response = client.get(f"/receipts/{receipt['id']}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['items'], [])
            self.assertEqual(self.upload(client=client).status_code, 409)

    def test_health_and_queries_report_database_unavailable(self):
        with patch('spending.api.connect', side_effect=sqlite3.OperationalError('test failure')):
            for url in ('/health', '/receipts', '/receipts/1'):
                with self.subTest(url=url):
                    if url == '/health':
                        response = self.client.get(url)
                    else:
                        with self.assertLogs('spending.api', level='ERROR'):
                            response = self.client.get(url)
                    self.assertEqual(response.status_code, 503)
                    self.assertNotIn('test failure', response.text)


if __name__ == '__main__':
    unittest.main()

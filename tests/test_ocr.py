"""Receipt parsing, OCR failure handling, HTTP persistence and real-engine checks."""

from contextlib import closing
from io import BytesIO
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from spending.api import create_app
from spending.database import connect
from spending.ocr_engine import LocalOCREngine, OCRDocument, OCRFailure, OCRPage, read_tsv
from spending.receipt_parser import parse_receipt

TEXT = 'TESCO\n21/10/2026\nMilk 1.20\nBread 2.30\nTOTAL GBP 3.50'


def synthetic_image():
    image = Image.new('RGB', (900, 500), 'white')
    ImageDraw.Draw(image).multiline_text((40, 35), TEXT, fill='black',
                                        font=ImageFont.load_default(size=38), spacing=16)
    return image


def document(text=TEXT):
    return OCRDocument(text, [OCRPage(1, text, 'tesseract', 0.95)], 0.95, 'test-engine')


class ReceiptParserTests(unittest.TestCase):
    def test_extracts_store_day_first_date_currency_total_and_items(self):
        parsed = parse_receipt(TEXT)
        self.assertEqual(parsed.supermarket_name, 'Tesco')
        self.assertEqual(parsed.purchase_date, '2026-10-21')
        self.assertEqual(parsed.currency, 'GBP')
        self.assertEqual(parsed.total_minor, 350)
        self.assertEqual([item.line_total_minor for item in parsed.items], [120, 230])
        self.assertEqual(parsed.warnings, [])

    def test_parses_decimal_comma_and_explicit_quantity(self):
        parsed = parse_receipt('LIDL\n2026-10-21\nRice 2 x 1,25 2,50\nTOTAL EUR 2,50')
        self.assertEqual(parsed.total_minor, 250)
        self.assertEqual(parsed.items[0].quantity, 2)
        self.assertEqual(parsed.items[0].unit_price_minor, 125)
        self.assertEqual(parsed.warnings, [])

    def test_missing_or_ambiguous_fields_are_not_invented(self):
        parsed = parse_receipt('Unknown store\nMilk 1.20\nTOTAL 1.20')
        self.assertIsNone(parsed.supermarket_name)
        self.assertIsNone(parsed.purchase_date)
        self.assertIsNone(parsed.currency)
        self.assertEqual(len(parsed.warnings), 3)
        ambiguous = parse_receipt(TEXT + '\n22/10/2026\nTOTAL GBP 4.50\nEUR')
        self.assertIsNone(ambiguous.purchase_date)
        self.assertIsNone(ambiguous.total_minor)
        self.assertIsNone(ambiguous.currency)

    def test_payment_subtotal_and_tax_lines_are_not_items(self):
        parsed = parse_receipt('TESCO\n21/10/26\nMilk 1.20\nSubtotal 1.20\nVAT 0.20\nTOTAL GBP 1.20\nVISA 1.20\nCHANGE 0.00')
        self.assertEqual(len(parsed.items), 1)
        self.assertEqual(parsed.purchase_date, '2026-10-21')
        self.assertEqual(parsed.total_minor, 120)

    def test_discounts_negative_lines_and_mismatches_require_review(self):
        parsed = parse_receipt('TESCO\n21/10/2026\nMilk 2 x 1.20 2.40\nDiscount -0.50\nRefund -1.00\nTOTAL GBP 1.90')
        self.assertEqual(len(parsed.items), 1)
        self.assertEqual(parsed.total_minor, 190)
        self.assertEqual(len(parsed.warnings), 3)

    def test_invalid_dates_and_empty_receipt_require_review(self):
        parsed = parse_receipt('TESCO\n31/02/2026\nTOTAL GBP 0.00')
        self.assertIsNone(parsed.purchase_date)
        self.assertEqual(parsed.total_minor, 0)
        self.assertIn('No grocery item lines identified.', parsed.warnings)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'receipt.png'
        with synthetic_image() as image:
            image.save(self.path)

    def test_tsv_groups_words_and_normalises_confidence(self):
        tsv = 'page_num\tblock_num\tpar_num\tline_num\tconf\ttext\n1\t1\t1\t1\t90\tMilk\n1\t1\t1\t1\t80\t1.20\n1\t1\t1\t2\t-1\t\n'
        text, confidence = read_tsv(tsv)
        self.assertEqual(text, 'Milk 1.20')
        self.assertAlmostEqual(confidence, 0.85)

    def test_tsv_quotes_in_recognised_text_do_not_consume_following_rows(self):
        tsv = 'page_num\tblock_num\tpar_num\tline_num\tconf\ttext\n1\t1\t1\t1\t90\t"Tesco\n1\t1\t1\t2\t80\tTOTAL £11.70\n'
        text, confidence = read_tsv(tsv)
        self.assertEqual(text, '"Tesco\nTOTAL £11.70')
        self.assertAlmostEqual(confidence, 0.85)

    def test_small_images_are_upscaled_and_large_images_keep_their_size(self):
        for size, expected in [((325, 872), (975, 2616)), ((400, 700), (800, 1400)), ((900, 500), (900, 500))]:
            with self.subTest(size=size), Image.new('RGB', size, 'white') as image:
                with patch('spending.ocr_engine.subprocess.run', return_value=Mock(stdout=b'')) as run:
                    LocalOCREngine()._image(image, 1)
                with Image.open(BytesIO(run.call_args.kwargs['input'])) as submitted:
                    self.assertEqual(submitted.size, expected)
                    self.assertEqual(submitted.mode, 'L')
                self.assertEqual(image.size, size)
                self.assertEqual(image.mode, 'RGB')

    def test_upscaling_respects_the_pixel_budget(self):
        with patch('spending.ocr_engine.MAX_PIXELS', 1000):
            with Image.new('RGB', (10, 50), 'white') as image:
                with patch('spending.ocr_engine.subprocess.run', return_value=Mock(stdout=b'')) as run:
                    LocalOCREngine()._image(image, 1)
                with Image.open(BytesIO(run.call_args.kwargs['input'])) as submitted:
                    self.assertEqual(submitted.size, (10, 50))
            with Image.new('RGB', (20, 51), 'white') as oversized:
                with self.assertRaisesRegex(OCRFailure, '20 million pixels'):
                    LocalOCREngine()._image(oversized, 1)

    @unittest.skipUnless(shutil.which('tesseract'), 'Tesseract binary not installed')
    def test_real_low_resolution_totals_are_read_and_mismatch_is_preserved(self):
        text = 'TESCO\nMilk 1.20\nBread 2.30\nTOTAL GBP 55.30\nCASH GBP 60.00\nCHANGE DUE 4.70\n17/10/22'
        with Image.new('RGB', (325, 400), 'white') as image:
            ImageDraw.Draw(image).multiline_text((15, 15), text, fill='black',
                                                font=ImageFont.load_default(size=14), spacing=8)
            image.save(self.path)
        result = LocalOCREngine().extract(self.path)
        parsed = parse_receipt(result.text)
        self.assertEqual(parsed.total_minor, 5530, result.text)
        self.assertIn('60.00', result.text)
        self.assertTrue(any('Item totals do not match' in warning for warning in parsed.warnings))

    def test_missing_engine_and_timeout_have_actionable_errors(self):
        for error, code in [(FileNotFoundError(), 503), (subprocess.TimeoutExpired('tesseract', 60), 504),
                            (subprocess.CalledProcessError(1, 'tesseract'), 503)]:
            with self.subTest(code=code), patch('spending.ocr_engine.subprocess.run', side_effect=error):
                with self.assertRaises(OCRFailure) as caught:
                    LocalOCREngine().extract(self.path)
                self.assertEqual(caught.exception.status_code, code)

    def test_blank_ocr_is_not_reported_as_success(self):
        with patch('spending.ocr_engine.subprocess.run', return_value=Mock(stdout=b'')):
            with self.assertRaisesRegex(OCRFailure, 'No readable text'):
                LocalOCREngine().extract(self.path)

    def test_pdf_text_layer_does_not_require_tesseract(self):
        path = self.path.with_suffix('.pdf')
        writer = PdfWriter()
        page = writer.add_blank_page(width=600, height=400)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 16 Tf 20 350 Td (TESCO) Tj 0 -25 Td (TOTAL GBP 3.50) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        writer.write(path)
        with patch('spending.ocr_engine.subprocess.run', side_effect=AssertionError('Text PDF should not use OCR')):
            result = LocalOCREngine().extract(path)
        self.assertIn('TOTAL GBP 3.50', result.text)
        self.assertEqual(result.pages[0].source, 'pdf_text')
        self.assertIsNone(result.confidence)

    def test_pdf_page_limit_is_enforced_before_rendering(self):
        path = self.path.with_suffix('.pdf')
        writer = PdfWriter()
        for _ in range(11):
            writer.add_blank_page(width=200, height=300)
        writer.write(path)
        with self.assertRaisesRegex(OCRFailure, '1 to 10 pages'):
            LocalOCREngine().extract(path)

    @unittest.skipUnless(shutil.which('tesseract'), 'Tesseract binary not installed')
    def test_real_tesseract_reads_synthetic_image(self):
        result = LocalOCREngine().extract(self.path)
        parsed = parse_receipt(result.text)
        self.assertEqual(parsed.total_minor, 350, result.text)
        self.assertEqual(len(parsed.items), 2, result.text)
        self.assertIsNotNone(result.confidence)

    @unittest.skipUnless(shutil.which('tesseract'), 'Tesseract binary not installed')
    def test_real_tesseract_reads_scanned_pdf(self):
        path = self.path.with_suffix('.pdf')
        with Image.open(self.path) as image:
            image.save(path, format='PDF', resolution=144)
        result = LocalOCREngine().extract(path)
        self.assertEqual(result.pages[0].source, 'tesseract')
        self.assertEqual(parse_receipt(result.text).total_minor, 350, result.text)


class OCRAPITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.database_path = root / 'ocr.db'
        self.upload_dir = root / 'uploads'
        self.engine = Mock(name='fake-ocr', **{'extract.return_value': document()})
        self.engine.name = 'test-ocr'
        self.client = self.enterContext(TestClient(create_app(self.database_path, self.upload_dir, ocr_engine=self.engine)))
        with synthetic_image() as image, BytesIO() as output:
            image.save(output, format='PNG')
            self.receipt = self.client.post('/receipts', files={'file': ('receipt.png', output.getvalue(), 'image/png')}).json()
        self.url = f"/receipts/{self.receipt['id']}/ocr"

    def test_success_persists_raw_text_provisional_fields_and_review_status(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200, response.text)
        run = response.json()
        self.assertEqual(run['status'], 'succeeded')
        self.assertEqual(run['output']['text'], TEXT)
        self.assertEqual(run['confidence'], 0.95)
        self.assertIsNotNone(run['completed_at'])
        detail = self.client.get(f"/receipts/{self.receipt['id']}").json()
        self.assertEqual(detail['status'], 'needs_review')
        self.assertEqual(detail['purchase_date'], '2026-10-21')
        self.assertEqual(detail['total_minor'], 350)
        self.assertEqual(len(detail['items']), 2)
        self.assertIsNone(detail['items'][0]['product_id'])
        with closing(connect(self.database_path)) as db:
            self.assertEqual(db.execute('SELECT name FROM Supermarket').fetchone()[0], 'Tesco')
            self.assertEqual(db.execute('SELECT count(*) FROM v_monthly_spending').fetchone()[0], 0)
        self.assertEqual(self.client.get(self.url).json()['id'], run['id'])

    def test_repeated_or_verified_receipt_ocr_does_not_overwrite(self):
        self.assertEqual(self.client.post(self.url).status_code, 200)
        self.assertEqual(self.client.post(self.url).status_code, 409)
        with closing(connect(self.database_path)) as db, db:
            db.execute("UPDATE Receipt SET status='verified'")
        self.assertEqual(self.client.post(self.url).status_code, 409)
        self.engine.extract.assert_called_once()

    def test_failures_are_saved_and_retry_creates_new_attempt(self):
        self.engine.extract.side_effect = OCRFailure('OCR timed out.', 504)
        self.assertEqual(self.client.post(self.url).status_code, 504)
        failed = self.client.get(self.url).json()
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['error_message'], 'OCR timed out.')
        self.assertIsNotNone(failed['completed_at'])
        self.engine.extract.side_effect = None
        succeeded = self.client.post(self.url).json()
        self.assertEqual(succeeded['status'], 'succeeded')
        self.assertNotEqual(succeeded['id'], failed['id'])
        with closing(connect(self.database_path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM ocr_runs').fetchone()[0], 2)

    def test_missing_or_external_file_fails_without_reading_it(self):
        for source in ('missing.png', '../outside.png'):
            with self.subTest(source=source):
                with closing(connect(self.database_path)) as db, db:
                    db.execute("UPDATE Receipt SET status='pending', source_path=?", (source,))
                self.assertEqual(self.client.post(self.url).status_code, 422)
                self.assertEqual(self.client.get(self.url).json()['status'], 'failed')
        self.engine.extract.assert_not_called()

    def test_unknown_receipt_and_no_attempt_return_404(self):
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post('/receipts/999/ocr').status_code, 404)
        self.assertEqual(self.client.get('/receipts/999/ocr').status_code, 404)

    def test_processing_is_visible_and_second_request_is_rejected(self):
        def while_processing(path):
            detail = self.client.get(f"/receipts/{self.receipt['id']}").json()
            self.assertEqual(detail['status'], 'processing')
            self.assertEqual(self.client.get(self.url).json()['status'], 'running')
            self.assertEqual(self.client.post(self.url).status_code, 409)
            return document()
        self.engine.extract.side_effect = while_processing
        self.assertEqual(self.client.post(self.url).status_code, 200)

    def test_existing_manual_items_are_preserved(self):
        with closing(connect(self.database_path)) as db, db:
            db.execute("INSERT INTO ReceiptItem(receipt_id, line_number, raw_description, line_total_minor) VALUES (?, 1, 'Manually entered', 100)", (self.receipt['id'],))
        self.assertEqual(self.client.post(self.url).status_code, 409)
        self.engine.extract.assert_not_called()

    def test_partial_extraction_saves_warnings_without_guessed_values(self):
        self.engine.extract.return_value = document('Some unreadable store\nMilk 1.20')
        run = self.client.post(self.url).json()
        self.assertEqual(run['status'], 'succeeded')
        self.assertTrue(run['output']['parsed']['warnings'])
        detail = self.client.get(f"/receipts/{self.receipt['id']}").json()
        self.assertIsNone(detail['supermarket_id'])
        self.assertIsNone(detail['total_minor'])
        self.assertEqual(detail['status'], 'needs_review')

    def test_persistence_failure_rolls_back_items_and_keeps_raw_result(self):
        with closing(connect(self.database_path)) as db, db:
            db.execute("CREATE TRIGGER reject_ocr_items BEFORE INSERT ON ReceiptItem BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with self.assertLogs('spending.ocr_service', level='ERROR'):
            self.assertEqual(self.client.post(self.url).status_code, 503)
        run = self.client.get(self.url).json()
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['output']['text'], TEXT)
        with closing(connect(self.database_path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM ReceiptItem').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM Supermarket').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT status FROM Receipt').fetchone()[0], 'failed')

    @unittest.skipUnless(shutil.which('tesseract'), 'Tesseract binary not installed')
    def test_real_ocr_upload_to_provisional_database_records(self):
        real_app = create_app(self.database_path, self.upload_dir, ocr_engine=LocalOCREngine())
        with TestClient(real_app) as client:
            response = client.post(self.url)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['output']['parsed']['total_minor'], 350)
            receipt = client.get(f"/receipts/{self.receipt['id']}").json()
            self.assertEqual(receipt['status'], 'needs_review')
            self.assertEqual(receipt['total_minor'], 350)
            self.assertEqual(len(receipt['items']), 2)


if __name__ == '__main__':
    unittest.main()

"""Receipt parsing, OCR failure handling, HTTP persistence and real-engine checks."""

from contextlib import closing
import importlib.util
from io import BytesIO
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from spending.api import create_app
from spending.database import connect
from spending.ocr_engine import RapidOCREngine, OCRDocument, OCRFailure, OCRPage
from spending.receipt_parser import parse_receipt

TEXT = 'TESCO\n21/10/2026\nMilk 1.20\nBread 2.30\nTOTAL GBP 3.50'


def synthetic_image():
    image = Image.new('RGB', (900, 500), 'white')
    ImageDraw.Draw(image).multiline_text((40, 35), TEXT, fill='black',
                                        font=ImageFont.load_default(size=38), spacing=16)
    return image


def document(text=TEXT):
    return OCRDocument(text, [OCRPage(1, text, 'rapidocr', 0.95)], 0.95, 'test-engine')


class ReceiptParserTests(unittest.TestCase):
    def test_extracts_store_day_first_date_currency_total_and_items(self):
        parsed = parse_receipt(TEXT)
        self.assertEqual(parsed.supermarket_name, 'Tesco')
        self.assertEqual(parsed.purchase_date, '2026-10-21')
        self.assertEqual(parsed.currency, 'GBP')
        self.assertEqual(parsed.total_pence, 350)
        self.assertEqual([item.original_pence for item in parsed.items], [120, 230])
        self.assertEqual(parsed.warnings, [])

    def test_parses_decimal_comma_and_explicit_quantity(self):
        parsed = parse_receipt('LIDL\n2026-10-21\nRice 2 x 1,25 2,50\nTOTAL EUR 2,50')
        self.assertEqual(parsed.total_pence, 250)
        self.assertEqual(parsed.items[0].quantity, 2)
        self.assertEqual(parsed.items[0].unit_price_pence, 125)
        self.assertEqual(parsed.warnings, [])

    def test_extracts_store_location_from_header_after_name(self):
        parsed = parse_receipt('''TESCO
ocr noise
Newtownbneda Extra lo loo1g
VAT Number: GB 220 4302 31
Bread
1.20
TOTAL
1.20''')
        self.assertEqual(parsed.supermarket_name, 'Tesco')
        self.assertEqual(parsed.supermarket_location, 'Newtownbneda Extra')

    def test_missing_or_ambiguous_fields_are_not_invented(self):
        parsed = parse_receipt('Unknown store\nMilk 1.20\nTOTAL 1.20')
        self.assertIsNone(parsed.supermarket_name)
        self.assertIsNone(parsed.purchase_date)
        self.assertIsNone(parsed.currency)
        self.assertEqual(len(parsed.warnings), 3)
        ambiguous = parse_receipt(TEXT + '\n22/10/2026\nTOTAL GBP 4.50\nEUR')
        self.assertIsNone(ambiguous.purchase_date)
        self.assertIsNone(ambiguous.total_pence)
        self.assertIsNone(ambiguous.currency)

    def test_payment_subtotal_and_tax_lines_are_not_items(self):
        parsed = parse_receipt('TESCO\n21/10/26\nMilk 1.20\nSubtotal 1.20\nVAT 0.20\nTOTAL GBP 1.20\nVISA 1.20\nCHANGE 0.00')
        self.assertEqual(len(parsed.items), 1)
        self.assertEqual(parsed.purchase_date, '2026-10-21')
        self.assertEqual(parsed.total_pence, 120)

    def test_cashback_and_change_amounts_are_ignored_after_total(self):
        parsed = parse_receipt('''Grocery Store
Bread
1.20
TOTAL
1.20
CASH
20.00
CHANGE\\CASHBACK
-18.80''')
        self.assertEqual([(item.raw_description, item.original_pence) for item in parsed.items], [('Bread', 120)])
        self.assertEqual(parsed.total_pence, 120)
        self.assertFalse(any('18.80' in warning for warning in parsed.warnings))

    def test_discounts_negative_lines_and_mismatches_require_review(self):
        parsed = parse_receipt('TESCO\n21/10/2026\nMilk 2 x 1.20 2.40\nDiscount -0.50\nRefund -1.00\nTOTAL GBP 1.90')
        self.assertEqual(len(parsed.items), 1)
        self.assertEqual(parsed.total_pence, 190)
        self.assertEqual(len(parsed.warnings), 3)

    def test_invalid_dates_and_empty_receipt_require_review(self):
        parsed = parse_receipt('TESCO\n31/02/2026\nTOTAL GBP 0.00')
        self.assertIsNone(parsed.purchase_date)
        self.assertEqual(parsed.total_pence, 0)
        self.assertIn('No grocery item lines identified.', parsed.warnings)

    def test_split_rows_pair_items_and_prices_in_ocr_order(self):
        parsed = parse_receipt('''10.10.26
Nectarines
3.40 A
0.758 kg × 4.49
Member promotion
-1.29
0.72 A
Bananas
0.804 kg × 0.90
Melon Honeydew
3.28 A
2 × 1.64
-1.10
TOTAL
5.01''')
        self.assertEqual(parsed.total_pence, 501)
        self.assertEqual(
            [(item.raw_description, item.quantity, item.unit_price_pence, item.discount_pence, item.original_pence) for item in parsed.items],
            [
                ('Nectarines', 0.758, 449, 129, 340),
                ('Bananas', 0.804, 90, 0, 72),
                ('Melon Honeydew', 2, 164, 110, 328),
            ],
        )
        self.assertNotIn('Item totals do not match the receipt total; check discounts, taxes and missing lines.', parsed.warnings)

    def test_promotion_labels_are_never_emitted_as_items(self):
        parsed = parse_receipt('''Bread
1.20
Member promotion
Loyalty Offers
-0.20
TOTAL
1.00''')
        self.assertEqual([(item.raw_description, item.discount_pence) for item in parsed.items], [('Bread', 20)])

    def test_discount_after_a_promotion_label_is_not_added_to_previous_item(self):
        parsed = parse_receipt('''Melon Honeydew
3.28
2 × 1.64
-1.10
Loyalty Offers
1.94
-0.65
TOTAL
2.18''')
        self.assertEqual([(item.raw_description, item.discount_pence) for item in parsed.items], [('Melon Honeydew', 110)])

    def test_items_and_base_prices_are_paired_once_in_ocr_order(self):
        parsed = parse_receipt('''Melon Honeydew
3.28
2 × 1.64
-1.10
Loyalty Offers
1.94
Red Grapes Punnet
-0.65
Loyalty Offers
0.69
Plain Flour
4.69
Large Free Range Eggs
0.79
Croissant Chocolate
TOTAL
7.98''')
        self.assertEqual(
            [(item.raw_description, item.original_pence, item.discount_pence) for item in parsed.items],
            [
                ('Melon Honeydew', 328, 110),
                ('Red Grapes Punnet', 194, 65),
                ('Plain Flour', 69, 0),
                ('Large Free Range Eggs', 469, 0),
                ('Croissant Chocolate', 79, 0),
            ],
        )

    def test_after_discount_price_is_consumed_without_becoming_next_item_price(self):
        parsed = parse_receipt('''Bread
2.00
Offer
-0.50
1.50
Whole Milk
1.20
TOTAL
2.70''')
        self.assertEqual(
            [(item.raw_description, item.original_pence, item.discount_pence) for item in parsed.items],
            [('Bread', 200, 50), ('Whole Milk', 120, 0)],
        )

    def test_multiple_ocr_discounts_are_never_combined_into_a_new_value(self):
        parsed = parse_receipt('''Melon Honeydew
3.28
2 × 1.64
Loyalty Offer
-1.10
-0.65
TOTAL
2.18''')
        self.assertEqual(parsed.items[0].discount_pence, 110)
        self.assertNotEqual(parsed.items[0].discount_pence, 175)
        self.assertIn('Adjustment/discount requires review: -0.65', parsed.warnings)
        self.assertEqual(
            set(parsed.to_dict()['items'][0]),
            {'raw_description', 'quantity', 'unit_price_pence', 'original_pence', 'discount_pence'},
        )

    def test_receipt_discount_total_must_be_an_explicit_ocr_amount(self):
        parsed = parse_receipt('''LIDL
21/10/2026
Bread
1.20
Offer
-0.20
TOTAL
1.00
TOTAL SAVINGS
0.20''')
        self.assertEqual(parsed.items[0].discount_pence, 20)
        self.assertEqual(parsed.total_discount_pence, 20)

    def test_math_mismatch_preserves_ocr_amount(self):
        parsed = parse_receipt('''Nectarines
3.50
0.758 kg × 4.49
TOTAL
3.50''')
        self.assertEqual(parsed.items[0].original_pence, 350)

    def test_tesco_separate_prices_promotions_and_vouchers_are_reconciled(self):
        parsed = parse_receipt('''TESCO
1 Custard Doughnuts
emuter
1 Chicken Crisps
£1.25
Flavour 140g
£2.25
Reduced To Clear
-£1.01
2 Toilet Tissues
£1.60
Coconut Oil Pack
£0.80 each
Subtotal:
£5.10
Coupons/vouchers:
-£0.50
TOTAL:
£3.59''')
        self.assertEqual(parsed.total_pence, 359)
        self.assertEqual(parsed.receipt_discount_pence, 50)
        self.assertEqual(
            [(item.raw_description, item.quantity, item.unit_price_pence, item.discount_pence, item.original_pence) for item in parsed.items],
            [
                ('Custard Doughnuts', 1, None, 0, 125),
                ('Chicken Crisps Flavour 140g', 1, None, 101, 225),
                ('Toilet Tissues', 2, 80, 0, 160),
            ],
        )
        self.assertNotIn('Item totals do not match the receipt total; check discounts, taxes and missing lines.', parsed.warnings)
        self.assertFalse(any(warning.startswith('Adjustment/discount requires review:') for warning in parsed.warnings))

    def test_symbol_led_line_continues_the_previous_product(self):
        parsed = parse_receipt('''TESCO
1 Butterkist Microwave Popcorn Sweet
£1.75
& Salted 3x60g
TOTAL
1.75''')
        self.assertEqual([(item.raw_description, item.original_pence) for item in parsed.items], [
            ('Butterkist Microwave Popcorn Sweet & Salted 3x60g', 175),
        ])

    def test_tesco_item_markers_do_not_replace_the_preceding_product(self):
        parsed = parse_receipt('''TESCO
SHREWSBURY CATTLE MARKET
TAPE MEASURE
x
£2.10
PROTEIN COOKIE
£1.80
TOTAL
3.90''')
        self.assertEqual([(item.raw_description, item.original_pence) for item in parsed.items], [
            ('TAPE MEASURE', 210),
            ('PROTEIN COOKIE', 180),
        ])


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'receipt.png'
        with synthetic_image() as image:
            image.save(self.path)

    def test_rapidocr_joins_lines_and_averages_confidence(self):
        recognizer = Mock(return_value=Mock(txts=['Milk 1.20', 'TOTAL GBP 1.20'], scores=[0.9, 0.8]))
        result = RapidOCREngine(recognizer=recognizer).extract(self.path)
        self.assertEqual(result.text, 'Milk 1.20\nTOTAL GBP 1.20')
        self.assertAlmostEqual(result.confidence, 0.85)
        self.assertEqual(result.pages[0].source, 'rapidocr')

    def test_small_images_are_upscaled_and_large_images_keep_their_size(self):
        for size, expected in [((325, 872), (975, 2616)), ((400, 700), (800, 1400)), ((900, 500), (900, 500))]:
            with self.subTest(size=size), Image.new('RGB', size, 'white') as image:
                submitted = []
                def recognise(prepared):
                    submitted.append((prepared.size, prepared.mode))
                    return Mock(txts=['Receipt'], scores=[0.9])
                RapidOCREngine(recognizer=recognise)._image(image, 1)
                self.assertEqual(submitted, [(expected, 'L')])
                self.assertEqual(image.size, size)
                self.assertEqual(image.mode, 'RGB')

    def test_tall_receipt_uses_overlapping_tiles_and_deduplicates_boundary_lines(self):
        recognizer = Mock(side_effect=[
            Mock(txts=['Milk', 'TOTAL'], scores=[0.9, 0.8]),
            Mock(txts=['TOTAL', '23/10/2026'], scores=[0.8, 0.7]),
        ])
        tall_path = Path(self.directory.name) / 'tall.png'
        with Image.new('L', (1000, 2400), 'white') as image:
            image.save(tall_path)
        engine = RapidOCREngine(recognizer=recognizer)
        full = engine.extract(tall_path)
        page = engine.supplement_footer(tall_path, full)
        self.assertEqual(page.text, 'Milk\nTOTAL\n23/10/2026')
        self.assertEqual([call.args[0].size for call in recognizer.call_args_list], [(1000, 2400), (700, 1600)])
        self.assertAlmostEqual(page.confidence, 0.75)

    def test_upscaling_respects_the_pixel_budget(self):
        with patch('spending.ocr_engine.MAX_PIXELS', 1000):
            with Image.new('RGB', (10, 50), 'white') as image:
                submitted = []
                recognizer = lambda prepared: (submitted.append(prepared.size) or Mock(txts=['Receipt'], scores=[0.9]))
                RapidOCREngine(recognizer=recognizer)._image(image, 1)
                self.assertEqual(submitted, [(10, 50)])
            with Image.new('RGB', (20, 51), 'white') as oversized:
                with self.assertRaisesRegex(OCRFailure, '20 million pixels'):
                    RapidOCREngine()._image(oversized, 1)

    def test_blank_ocr_is_not_reported_as_success(self):
        with self.assertRaisesRegex(OCRFailure, 'No readable text'):
            RapidOCREngine(recognizer=Mock(return_value=Mock(txts=[], scores=[]))).extract(self.path)

    def test_pdf_text_layer_does_not_require_rapidocr(self):
        path = self.path.with_suffix('.pdf')
        writer = PdfWriter()
        page = writer.add_blank_page(width=600, height=400)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 16 Tf 20 350 Td (TESCO) Tj 0 -25 Td (TOTAL GBP 3.50) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        writer.write(path)
        recognizer = Mock(side_effect=AssertionError('Text PDF should not use OCR'))
        result = RapidOCREngine(recognizer=recognizer).extract(path)
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
            RapidOCREngine(recognizer=Mock()).extract(path)

    @unittest.skipUnless(importlib.util.find_spec('rapidocr'), 'RapidOCR is not installed')
    def test_real_rapidocr_reads_synthetic_image(self):
        result = RapidOCREngine().extract(self.path)
        parsed = parse_receipt(result.text)
        self.assertEqual(parsed.total_pence, 350, result.text)
        self.assertEqual(len(parsed.items), 2, result.text)
        self.assertIsNotNone(result.confidence)

    @unittest.skipUnless(importlib.util.find_spec('rapidocr'), 'RapidOCR is not installed')
    def test_real_rapidocr_reads_scanned_pdf(self):
        path = self.path.with_suffix('.pdf')
        with Image.open(self.path) as image:
            image.save(path, format='PDF', resolution=144)
        result = RapidOCREngine().extract(path)
        self.assertEqual(result.pages[0].source, 'rapidocr')
        self.assertEqual(parse_receipt(result.text).total_pence, 350, result.text)


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
        self.assertEqual(detail['total_pence'], 350)
        self.assertEqual(len(detail['items']), 2)
        self.assertIsNone(detail['items'][0]['product_id'])
        with closing(connect(self.database_path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM Supermarket').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM ReceiptItem').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM v_monthly_spending').fetchone()[0], 0)
        self.assertEqual(self.client.get(self.url).json()['id'], run['id'])
        self.engine.supplement_footer.assert_not_called()

    def test_missing_date_retries_the_footer_before_persisting(self):
        self.engine.extract.return_value = document('TESCO\nMilk 1.20\nTOTAL GBP 1.20')
        self.engine.supplement_footer.return_value = document(TEXT)
        self.assertEqual(self.client.post(self.url).status_code, 200)
        detail = self.client.get(f"/receipts/{self.receipt['id']}").json()
        self.engine.supplement_footer.assert_called_once()
        self.assertEqual(detail['purchase_date'], '2026-10-21')

    def test_lidl_quantity_unit_price_and_discount_remain_in_ocr_draft(self):
        self.engine.extract.return_value = document(
            'LIDL\n10.10.26\nMelon Honeydew\n3.28 A\n2 × 1.64\n'
            'Lidl Plus Offer\n-1.10\nTOTAL\n2.18'
        )
        self.assertEqual(self.client.post(self.url).status_code, 200)
        detail = self.client.get(f"/receipts/{self.receipt['id']}").json()
        self.assertEqual(detail['total_pence'], 218)
        self.assertEqual(detail['discount_pence'], 0)
        self.assertEqual(detail['items'][0]['raw_description'], 'Melon Honeydew')
        self.assertEqual(detail['items'][0]['quantity'], 2)
        self.assertEqual(detail['items'][0]['unit_price_pence'], 164)
        self.assertEqual(detail['items'][0]['original_pence'], 328)
        self.assertEqual(detail['items'][0]['discount_pence'], 110)

    def test_tesco_voucher_discount_persists_at_receipt_level(self):
        self.engine.extract.return_value = document(
            'TESCO\n1 Doughnuts\n£1.25\nSubtotal\n£1.25\nCoupons/vouchers:\n-£0.50\nTOTAL\n£0.75'
        )
        self.assertEqual(self.client.post(self.url).status_code, 200)
        detail = self.client.get(f"/receipts/{self.receipt['id']}").json()
        self.assertEqual(detail['total_pence'], 75)
        self.assertEqual(detail['discount_pence'], 0)
        self.assertEqual(detail['voucher_pence'], 50)

    def test_review_correction_replaces_items_and_records_audit_values(self):
        self.assertEqual(self.client.post(self.url).status_code, 200)
        response = self.client.patch(
            f"/receipts/{self.receipt['id']}/review",
            json={
                'supermarket_name': 'Tesco Extra',
                'total_pence': 351,
                'items': [
                    {'raw_description': 'Milk', 'quantity': 1, 'unit_price_pence': 120, 'original_pence': 120},
                    {'raw_description': 'Bread', 'quantity': 1, 'unit_price_pence': 231, 'original_pence': 231},
                ],
                'corrected_by': 'Helen',
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'needs_review')
        self.assertEqual([item['original_pence'] for item in response.json()['items']], [120, 231])
        with closing(connect(self.database_path)) as db:
            rows = db.execute(
                'SELECT field_name, original_value, corrected_value, corrected_by FROM correction_audit ORDER BY id'
            ).fetchall()
        self.assertEqual([row['field_name'] for row in rows], ['supermarket_name', 'total_pence', 'items'])
        self.assertTrue(all(row['corrected_by'] == 'Helen' for row in rows))
        self.assertIn('Tesco', rows[0]['original_value'])
        self.assertIn('Tesco Extra', rows[0]['corrected_value'])

    def test_only_review_ready_receipts_can_be_corrected(self):
        response = self.client.patch(
            f"/receipts/{self.receipt['id']}/review", json={'total_pence': 350}
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail'], 'Only receipts awaiting review can be corrected.')

    def test_verification_requires_reconciled_review_and_updates_spending(self):
        self.assertEqual(self.client.post(self.url).status_code, 200)
        response = self.client.post(
            f"/receipts/{self.receipt['id']}/verify", json={'corrected_by': 'Helen'}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'verified')
        with closing(connect(self.database_path)) as db:
            spending = db.execute('SELECT total_pence FROM v_monthly_spending').fetchone()
            audit = db.execute(
                "SELECT field_name, corrected_value, corrected_by FROM correction_audit WHERE field_name='status'"
            ).fetchone()
        self.assertEqual(spending['total_pence'], 350)
        self.assertEqual((audit['field_name'], audit['corrected_value'], audit['corrected_by']), ('status', '"verified"', 'Helen'))

    def test_verification_matches_a_leading_brand_to_the_product(self):
        self.engine.extract.return_value = document(
            'TESCO\n21/10/2026\nWalkers Crisps 140g\n£2.25\nTOTAL GBP 2.25'
        )
        self.assertEqual(self.client.post(self.url).status_code, 200)
        self.assertEqual(self.client.post(f"/receipts/{self.receipt['id']}/verify", json={}).status_code, 200)
        with closing(connect(self.database_path)) as db:
            item = db.execute('''
                SELECT i.name, b.name AS brand_name FROM ReceiptItem r JOIN Item i ON i.id=r.product_id
                JOIN Brand b ON b.id=i.brand_id WHERE r.receipt_id=?
            ''', (self.receipt['id'],)).fetchone()
        self.assertEqual((item['name'], item['brand_name']), ('Crisps', 'Walkers'))

    def test_existing_item_name_does_not_imply_its_brand_on_a_new_receipt(self):
        with closing(connect(self.database_path)) as db, db:
            walkers = db.execute("SELECT id FROM Brand WHERE name='Walkers'").fetchone()['id']
            db.execute("INSERT INTO Item(name, brand_id, pack_size, pack_unit) VALUES ('Crisps', ?, 140, 'g')", (walkers,))
        self.engine.extract.return_value = document(
            'TESCO\n21/10/2026\nCrisps 140g\n£2.25\nTOTAL GBP 2.25'
        )
        self.assertEqual(self.client.post(self.url).status_code, 200)
        item = self.client.get(f"/receipts/{self.receipt['id']}").json()['items'][0]
        self.assertIsNone(item['brand_id'])
        self.assertEqual((item['brand_name'], item['brand_source']), ('Tesco', 'supermarket'))
        self.assertEqual(self.client.post(f"/receipts/{self.receipt['id']}/verify", json={}).status_code, 200)
        with closing(connect(self.database_path)) as db:
            brands = {row['name'] for row in db.execute('''
                SELECT b.name FROM Item i JOIN Brand b ON b.id=i.brand_id
                WHERE i.name='Crisps' AND i.pack_size=140 AND i.pack_unit='g'
            ''')}
        self.assertEqual(brands, {'Tesco', 'Walkers'})

    def test_unknown_brand_candidate_is_not_saved_as_an_alias(self):
        self.engine.extract.return_value = document(
            'TESCO\n21/10/2026\nAcme Crisps 140g\n£2.25\nTOTAL GBP 2.25'
        )
        self.assertEqual(self.client.post(self.url).status_code, 200)
        detail = self.client.get(f"/receipts/{self.receipt['id']}").json()
        self.assertIsNone(detail['items'][0]['brand_id'])
        self.assertEqual((detail['items'][0]['brand_name'], detail['items'][0]['brand_source']),
                         ('Acme', 'candidate'))
        item = detail['items'][0]
        item['brand_name'] = 'Acme Foods'
        response = self.client.patch(
            f"/receipts/{self.receipt['id']}/review", json={'items': [item]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.post(f"/receipts/{self.receipt['id']}/verify", json={}).status_code, 200)
        with closing(connect(self.database_path)) as db:
            product = db.execute('''
                SELECT i.name, b.name AS brand_name FROM Item i JOIN Brand b ON b.id=i.brand_id
            ''').fetchone()
            alias = db.execute("SELECT 1 FROM BrandAlias WHERE alias='Acme'").fetchone()
        self.assertEqual((product['name'], product['brand_name']), ('Acme Crisps', 'Acme Foods'))
        self.assertIsNone(alias)

    def test_final_brand_does_not_strip_a_candidate_from_the_product_name(self):
        self.engine.extract.return_value = document(
            'LIDL\n21/10/2026\nCroissant Chocolate\n£0.79\nTOTAL GBP 0.79'
        )
        self.assertEqual(self.client.post(self.url).status_code, 200)
        detail = self.client.get(f"/receipts/{self.receipt['id']}").json()
        item = detail['items'][0]
        self.assertEqual((item['brand_name'], item['brand_source']), ('Croissant', 'candidate'))
        item['brand_name'] = 'Lidl'
        item['brand_candidate'] = 'Croissant'
        item['brand_source'] = 'candidate'
        response = self.client.patch(f"/receipts/{self.receipt['id']}/review", json={'items': [item]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.post(f"/receipts/{self.receipt['id']}/verify", json={}).status_code, 200)
        with closing(connect(self.database_path)) as db:
            product = db.execute('SELECT name FROM Item').fetchone()
            alias = db.execute("SELECT 1 FROM BrandAlias WHERE alias='Croissant'").fetchone()
        self.assertEqual(product['name'], 'Croissant Chocolate')
        self.assertIsNone(alias)

    def test_unbranded_item_uses_editable_supermarket_default(self):
        self.engine.extract.return_value = document(
            'TESCO\n21/10/2026\nPlain Flour\n£1.20\nTOTAL GBP 1.20'
        )
        self.assertEqual(self.client.post(self.url).status_code, 200)
        item = self.client.get(f"/receipts/{self.receipt['id']}").json()['items'][0]
        self.assertIsNone(item['brand_id'])
        self.assertEqual((item['brand_name'], item['brand_source']), ('Tesco', 'supermarket'))
        self.assertEqual(self.client.post(f"/receipts/{self.receipt['id']}/verify", json={}).status_code, 200)

    def test_repeated_or_verified_receipt_ocr_does_not_overwrite(self):
        self.assertEqual(self.client.post(self.url).status_code, 200)
        self.assertEqual(self.client.post(self.url).status_code, 409)
        self.assertEqual(self.client.post(f"/receipts/{self.receipt['id']}/verify", json={}).status_code, 200)
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
            db.execute("INSERT INTO ReceiptItem(receipt_id, line_number, raw_description, original_pence) VALUES (?, 1, 'Manually entered', 100)", (self.receipt['id'],))
        self.assertEqual(self.client.post(self.url).status_code, 409)
        self.engine.extract.assert_not_called()

    def test_partial_extraction_saves_warnings_without_guessed_values(self):
        self.engine.extract.return_value = document('Some unreadable store\nMilk 1.20')
        run = self.client.post(self.url).json()
        self.assertEqual(run['status'], 'succeeded')
        self.assertTrue(run['output']['parsed']['warnings'])
        detail = self.client.get(f"/receipts/{self.receipt['id']}").json()
        self.assertIsNone(detail['supermarket_id'])
        self.assertIsNone(detail['total_pence'])
        self.assertEqual(detail['status'], 'needs_review')

    def test_ocr_keeps_items_out_of_database_until_verification(self):
        with closing(connect(self.database_path)) as db, db:
            db.execute("CREATE TRIGGER reject_ocr_items BEFORE INSERT ON ReceiptItem BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        self.assertEqual(self.client.post(self.url).status_code, 200)
        run = self.client.get(self.url).json()
        self.assertEqual(run['status'], 'succeeded')
        self.assertEqual(run['output']['text'], TEXT)
        with closing(connect(self.database_path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM ReceiptItem').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM Supermarket').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT status FROM Receipt').fetchone()[0], 'needs_review')

    @unittest.skipUnless(importlib.util.find_spec('rapidocr'), 'RapidOCR is not installed')
    def test_real_ocr_upload_to_provisional_database_records(self):
        real_app = create_app(self.database_path, self.upload_dir, ocr_engine=RapidOCREngine())
        with TestClient(real_app) as client:
            response = client.post(self.url)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['output']['parsed']['total_pence'], 350)
            receipt = client.get(f"/receipts/{self.receipt['id']}").json()
            self.assertEqual(receipt['status'], 'needs_review')
            self.assertEqual(receipt['total_pence'], 350)
            self.assertEqual(len(receipt['items']), 2)


if __name__ == '__main__':
    unittest.main()

"""Receipt parsing, OCR failure handling, HTTP persistence and real-engine checks."""

from contextlib import closing
import importlib.util
from io import BytesIO
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from spending.api import create_app
from spending.database import connect
from spending.ocr_engine import RapidOCREngine, OCRDocument, OCRFailure, OCRPage
from spending.receipt_parser import parse_receipt

TEXT = 'TESCO\n21/10/2026\nMilk £1.20\nBread £2.30\nTOTAL GBP £3.50'


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
        self.assertEqual(parsed.date_candidates, ['2026-10-21'])
        self.assertEqual(parsed.currency, 'GBP')
        self.assertEqual(parsed.total_pence, 350)
        self.assertEqual([item.original_pence for item in parsed.items], [120, 230])
        self.assertEqual(parsed.warnings, [])


    def test_extracts_store_location_from_header_after_name(self):
        parsed = parse_receipt('''TESCO
ocr noise
Newtownbneda Extra lo loo1g
VAT Number: GB 220 4302 31
Bread
£1.20
TOTAL
£1.20''')
        self.assertEqual(parsed.supermarket_name, 'Tesco')
        self.assertEqual(parsed.supermarket_location, 'Newtownbneda Extra')


    def test_any_total_label_is_used_as_the_receipt_total(self):
        parsed = parse_receipt('Bread\n£1.20\nTotal payable GBP £1.20')
        self.assertEqual(parsed.total_pence, 120)

    def test_short_ocr_prefix_before_balance_due_is_ignored(self):
        parsed = parse_receipt('''Sainsbury's
*HERO ST/DRW B/BGX12
£3.75
Nectar Price Saving
-£0.75
*WOTSITS CRUNCHY CHE
£2.50
Nectar Price Saving
-£1.00
*GET MORE MULTIVITS
£2.00
Nectar Price Saving
-£0.80
3 BALANCE DUE
£5.70
MASTERCARD
£5.70''')
        self.assertEqual(parsed.total_pence, 570)

    def test_first_price_uses_the_previous_line_instead_of_a_numbered_header(self):
        parsed = parse_receipt('''Sainsbury's
Good food for all of us
FORESTSIDE
Sainsbury's Supermarkets Ltd
33 Charterhouse Street London EC1M 6HA
www.sainsburys.co.uk
Vat Number : 660 4548 36
*HERO ST/DRW B/BGX12
£3.75
*WOTSITS CRUNCHY CHE
£2.50
3 BALANCE DUE
£6.25''')
        self.assertEqual(
            [(item.raw_description, item.quantity, item.original_pence) for item in parsed.items],
            [('*HERO ST/DRW B/BGX12', 1, 375), ('*WOTSITS CRUNCHY CHE', 1, 250)],
        )

    def test_total_label_can_appear_later_in_a_summary_line(self):
        parsed = parse_receipt('Bread\n£1.20\nPayment summary — Amount Due\n£1.20')
        self.assertEqual(parsed.total_pence, 120)

    def test_missing_or_ambiguous_fields_are_not_invented(self):
        parsed = parse_receipt('Unknown store\nMilk £1.20\nTOTAL £1.20')
        self.assertIsNone(parsed.supermarket_name)
        self.assertIsNone(parsed.purchase_date)
        self.assertEqual(parsed.currency, 'GBP')
        self.assertEqual(len(parsed.warnings), 2)
        ambiguous = parse_receipt(TEXT + '\n22/10/2026\nTOTAL GBP €4.50\nEUR')
        self.assertIsNone(ambiguous.purchase_date)
        self.assertEqual(ambiguous.date_candidates, ['2026-10-21', '2026-10-22'])
        self.assertIsNone(ambiguous.total_pence)
        self.assertIsNone(ambiguous.currency)

    def test_payment_subtotal_and_tax_lines_are_not_items(self):
        parsed = parse_receipt('TESCO\n21/10/26\nMilk £1.20\nSubtotal £1.20\nVAT £0.20\nTOTAL GBP £1.20\nVISA £1.20\nCHANGE £0.00')
        self.assertEqual(len(parsed.items), 1)
        self.assertEqual(parsed.purchase_date, '2026-10-21')
        self.assertEqual(parsed.total_pence, 120)

    def test_cashback_and_change_amounts_are_ignored_after_total(self):
        parsed = parse_receipt('''Grocery Store
Bread
£1.20
TOTAL
£1.20
CASH
£20.00
CHANGE\\CASHBACK
-£18.80''')
        self.assertEqual([(item.raw_description, item.original_pence) for item in parsed.items], [('Bread', 120)])
        self.assertEqual(parsed.total_pence, 120)
        self.assertFalse(any('18.80' in warning for warning in parsed.warnings))


    def test_invalid_dates_and_empty_receipt_require_review(self):
        parsed = parse_receipt('TESCO\n31/02/2026\nTOTAL GBP £0.00')
        self.assertIsNone(parsed.purchase_date)
        self.assertEqual(parsed.total_pence, 0)
        self.assertIn('No grocery item lines identified.', parsed.warnings)

    def test_text_month_dates_support_common_receipt_formats(self):
        cases = {
            '31 Oct 2026': '2026-10-31',
            '31 October 2026': '2026-10-31',
            '31st Oct 26': '2026-10-31',
            'Oct 31, 2026': '2026-10-31',
            'October 31st 26': '2026-10-31',
            '31OCT2026': '2026-10-31',
            '310CT2026': '2026-10-31',
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(parse_receipt(f'TESCO\n{value}\nTOTAL £0.00').purchase_date, expected)
        self.assertIsNone(parse_receipt('TESCO\n31 Feb 2026\nTOTAL £0.00').purchase_date)








    def test_unmarked_decimals_are_not_amounts(self):
        parsed = parse_receipt('Unknown Shop\nBread 1.20\nTOTAL 1.20')
        self.assertIsNone(parsed.total_pence)
        self.assertEqual(parsed.items, [])

    def test_receipt_selects_bare_decimal_mode_from_currency_context(self):
        parsed = parse_receipt('''LIDL
GBP
Pineapple
0.98 A
Tempura King Prawns
4.58 A
TOTAL
5.43''')
        self.assertEqual(parsed.total_pence, 543)
        self.assertEqual(
            [(item.raw_description, item.original_pence) for item in parsed.items],
            [('Pineapple', 98), ('Tempura King Prawns', 458)],
        )

    def test_negative_amount_is_the_previous_items_discount(self):
        parsed = parse_receipt('''LIDL
GBP
Bread
1.20 A
Lidl Plus Offer
-0.20
TOTAL
1.00''')
        self.assertEqual(
            [(item.raw_description, item.original_pence, item.discount_pence)
             for item in parsed.items],
            [('Bread', 120, 20)],
        )

    def test_vat_number_and_url_end_the_receipt_header(self):
        parsed = parse_receipt('''TESCO
Header price
£9.99
VAT Number GB 220 4302 31
www.tesco.com
Bread
£1.20
TOTAL
£1.20''')
        self.assertEqual(
            [(item.raw_description, item.original_pence) for item in parsed.items],
            [('Bread', 120)],
        )

    def test_consecutive_text_lines_are_joined_before_the_amount(self):
        parsed = parse_receipt('''TESCO
GBP
Butterkist Microwave Popcorn Sweet
& Salted 3x60g
£1.75
TOTAL
£1.75''')
        self.assertEqual(
            [(item.raw_description, item.original_pence) for item in parsed.items],
            [('Butterkist Microwave Popcorn Sweet & Salted 3x60g', 175)],
        )

    def test_integer_quantity_and_two_ocr_amounts_are_math_checked(self):
        valid = parse_receipt('''TESCO
GBP
Chocolate Donuts
£6.00
3
£2.00
TOTAL
£6.00''')
        self.assertEqual(
            [(item.quantity, item.unit_price_pence, item.original_pence) for item in valid.items],
            [(3, 200, 600)],
        )
        self.assertFalse(any('quantity × unit price' in warning for warning in valid.warnings))

        invalid = parse_receipt('''TESCO
GBP
Chocolate Donuts
£5.00
3
£2.00
TOTAL
£5.00''')
        self.assertEqual(
            [(item.quantity, item.unit_price_pence, item.original_pence) for item in invalid.items],
            [(3, 200, 500)],
        )
        self.assertTrue(any('quantity × unit price' in warning for warning in invalid.warnings))

    def test_quantity_and_unit_price_positions_are_not_fixed(self):
        quantity_before_original = parse_receipt('''TESCO
GBP
Chocolate Donuts
3
£6.00
£2.00
TOTAL
£6.00''')
        unit_before_original = parse_receipt('''TESCO
GBP
Chocolate Donuts
£2.00
3
£6.00
TOTAL
£6.00''')
        for parsed in (quantity_before_original, unit_before_original):
            item = parsed.items[0]
            self.assertEqual((item.quantity, item.unit_price_pence, item.original_pence), (3, 200, 600))
            self.assertFalse(any('quantity × unit price' in warning for warning in parsed.warnings))

    def test_quantity_price_token_accepts_optional_multiplication_marker(self):
        for token in ('2 x 2.29', '2 × £2.29', '2 @ 2.29', '2 2.29'):
            with self.subTest(token=token):
                parsed = parse_receipt(f'''LIDL
GBP
Tempura King Prawns
4.58 A
{token}
Lidl Plus Offer
-0.58
TOTAL
4.00''')
                self.assertEqual(
                    [(item.raw_description, item.quantity, item.unit_price_pence,
                      item.original_pence, item.discount_pence) for item in parsed.items],
                    [('Tempura King Prawns', 2, 229, 458, 58)],
                )

    def test_math_mismatch_preserves_ocr_amount(self):
        parsed = parse_receipt('''Nectarines
£3.50
0.758 kg × £4.49
TOTAL
£3.50''')
        self.assertEqual(parsed.items[0].original_pence, 350)

    def test_promotion_markers_group_items_and_keep_each_discount(self):
        for marker in ('3 for £2.00', '3 for 2.00', 'MnM 3 for £2.00',
                       '2 Fr £7.50', '3 for 2', 'CC £1.00', 'CC 1'):
            with self.subTest(marker=marker):
                parsed = parse_receipt(f'''LIDL
GBP
Chocolate Twist
£0.80
{marker}
Savings
-£0.06
-£0.13
TOTAL £0.61''')
                self.assertEqual([item.raw_description for item in parsed.items], ['Chocolate Twist'])
                item = parsed.items[0]
                self.assertEqual(item.original_pence, 80)
                self.assertEqual(item.discount_pence, 19)
                self.assertEqual([discount.amount_pence for discount in item.discounts], [6, 13])
                self.assertEqual(item.promotions[0].marker_text, marker)
                self.assertEqual(
                    {discount.promotion_group for discount in item.discounts},
                    {item.promotions[0].group},
                )

    def test_multi_buy_group_spans_its_advertised_item_quantity(self):
        parsed = parse_receipt('''LIDL
GBP
Chocolate Twist
£0.80
MnM 3for £2.00
-£0.13
Croissant Butter
£0.79
-£0.12
Danish Pastry
£0.79
-£0.12
TOTAL £2.01''')
        self.assertEqual(len(parsed.items), 3)
        self.assertEqual(
            {item.promotions[0].group for item in parsed.items},
            {'promotion-1'},
        )
        self.assertEqual(
            [item.discounts[0].promotion_group for item in parsed.items],
            ['promotion-1', 'promotion-1', 'promotion-1'],
        )

    def test_quantity_column_layout_merges_wrapped_names_and_limits_multi_buy(self):
        parsed = parse_receipt('''TESCO
GBP
VAT Number: GB 220 4302 31
1 Caesar & Smoked Bacon £3.50
Coleslaw 270g
2 Cola Zero £10.40
Soft Drink 12 x 330ml
£5.20 each
Cc Any 2 For £7 -£3.40
TOTAL £10.50''')
        self.assertEqual(
            [(item.raw_description, item.quantity, item.unit_price_pence,
              item.original_pence, item.discount_pence) for item in parsed.items],
            [
                ('Caesar & Smoked Bacon Coleslaw 270g', 1, None, 350, 0),
                ('Cola Zero Soft Drink 12 x 330ml', 2, 520, 1040, 340),
            ],
        )
        self.assertEqual(len(parsed.items[1].promotions), 1)
        self.assertEqual(parsed.items[1].promotions[0].advertised_quantity, 2)

    def test_receipt_coupon_is_kept_separate_from_item_discounts(self):
        parsed = parse_receipt('''TESCO
GBP
VAT Number: GB 220 4302 31
1 Bread £3.00
1 Milk £2.00
Coupons/vouchers: -£1.00
TOTAL: £4.00''')
        self.assertEqual(parsed.receipt_discount_pence, 100)
        self.assertEqual(sum(item.discount_pence for item in parsed.items), 0)

    def test_sales_voucher_heading_does_not_end_the_item_section(self):
        parsed = parse_receipt('''B&M Retail Ltd
GBP
SALES VOUCHER
Dog Treats £5.00
Sub Total: £5.00
TOTAL £5.00''')
        self.assertEqual(
            [(item.raw_description, item.original_pence) for item in parsed.items],
            [('Dog Treats', 500)],
        )





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

    def test_rapidocr_rebuilds_visual_rows_from_text_boxes(self):
        recognizer = Mock(return_value=Mock(
            txts=['£0.40', '1 Tesco Bananas Loose', '£3.50', '1 Coleslaw'],
            scores=[0.9, 0.9, 0.9, 0.9],
            boxes=np.array([
                [[700, 100], [780, 100], [780, 125], [700, 125]],
                [[20, 102], [300, 102], [300, 127], [20, 127]],
                [[700, 140], [780, 140], [780, 165], [700, 165]],
                [[20, 142], [250, 142], [250, 167], [20, 167]],
            ]),
        ))
        result = RapidOCREngine(recognizer=recognizer).extract(self.path)
        self.assertEqual(
            result.text,
            '1 Tesco Bananas Loose £0.40\n1 Coleslaw £3.50',
        )
        self.assertAlmostEqual(result.confidence, 0.9)
        self.assertEqual(result.pages[0].source, 'rapidocr')

    def test_small_images_are_upscaled_and_large_images_keep_their_size(self):
        for size, expected in [((325, 872), (975, 2616)), ((400, 700), (800, 1400)), ((900, 500), (900, 500))]:
            with self.subTest(size=size), Image.new('RGB', size, 'white') as image:
                submitted = []
                def recognise(prepared, **_options):
                    submitted.append((prepared.size, prepared.mode))
                    return Mock(txts=['Receipt'], scores=[0.9])
                RapidOCREngine(recognizer=recognise)._image(image, 1)
                self.assertEqual(submitted, [(expected, 'RGB')])
                self.assertEqual(image.size, size)
                self.assertEqual(image.mode, 'RGB')

    def test_receipt_region_is_located_before_ocr(self):
        with Image.new('RGB', (1000, 800), '#303030') as photograph:
            ImageDraw.Draw(photograph).polygon(
                [(190, 80), (820, 120), (770, 730), (220, 690)], fill='white',
            )
            located = RapidOCREngine._locate_receipt(photograph)
            self.addCleanup(located.close)
            self.assertLess(located.width, photograph.width)
            self.assertLess(located.height, photograph.height)
            self.assertGreater(located.width, 500)
            self.assertGreater(located.height, 500)

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
                recognizer = lambda prepared, **_options: (submitted.append(prepared.size) or Mock(txts=['Receipt'], scores=[0.9]))
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
        self.assertEqual([item.original_pence for item in parsed.items], [120, 230], result.text)
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
        self.assertEqual(detail['supermarket_name'], 'Tesco')
        self.assertEqual(detail['expense_category_name'], 'Groceries')
        self.assertEqual(detail['purchase_date'], '2026-10-21')
        self.assertEqual(detail['total_pence'], 350)
        self.assertEqual(len(detail['items']), 2)
        self.assertIsNone(detail['items'][0]['product_id'])
        with closing(connect(self.database_path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM Supermarket').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM ReceiptItem').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM v_monthly_spending').fetchone()[0], 0)
        self.assertEqual(self.client.get(self.url).json()['id'], run['id'])
        self.assertEqual(self.client.get('/receipts').json()['items'][0]['supermarket_name'], 'Tesco')
        self.engine.supplement_footer.assert_not_called()

    def test_missing_date_retries_the_footer_before_persisting(self):
        self.engine.extract.return_value = document('TESCO\nMilk £1.20\nTOTAL GBP £1.20')
        self.engine.supplement_footer.return_value = document(TEXT)
        self.assertEqual(self.client.post(self.url).status_code, 200)
        detail = self.client.get(f"/receipts/{self.receipt['id']}").json()
        self.engine.supplement_footer.assert_called_once()
        self.assertEqual(detail['purchase_date'], '2026-10-21')



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

    def test_verification_persists_discount_reasons_and_promotion_group(self):
        text = '''LIDL
21/10/2026
Chocolate Twist
£0.80
3 for £2.00
Savings
-£0.06
-£0.13
TOTAL £0.61'''
        self.engine.extract.return_value = document(text)
        self.assertEqual(self.client.post(self.url).status_code, 200)
        response = self.client.post(f"/receipts/{self.receipt['id']}/verify", json={})
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()['items'][0]
        self.assertEqual([discount['amount_pence'] for discount in item['discounts']], [6, 13])
        self.assertEqual(item['promotions'][0]['marker_text'], '3 for £2.00')
        with closing(connect(self.database_path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM ItemDiscount').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT count(*) FROM PromotionGroup').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM ReceiptItemPromotionGroup').fetchone()[0], 1)

    def test_manual_b_and_m_supermarket_is_created_when_the_receipt_is_verified(self):
        self.assertEqual(self.client.post(self.url).status_code, 200)
        response = self.client.patch(
            f"/receipts/{self.receipt['id']}/review",
            json={'supermarket_name': 'B&M'},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.post(f"/receipts/{self.receipt['id']}/verify", json={}).status_code, 200)
        with closing(connect(self.database_path)) as db:
            store = db.execute(
                "SELECT name FROM Supermarket WHERE name='B&M' COLLATE NOCASE"
            ).fetchone()
        self.assertEqual(store['name'], 'B&M')

    def test_verification_matches_a_leading_brand_to_the_product(self):
        self.engine.extract.return_value = document(
            'TESCO\n21/10/2026\nWalkers Crisps 140g\n£2.25\nTOTAL GBP £2.25'
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
            'TESCO\n21/10/2026\nCrisps 140g\n£2.25\nTOTAL GBP £2.25'
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
            'TESCO\n21/10/2026\nAcme Crisps 140g\n£2.25\nTOTAL GBP £2.25'
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
                SELECT i.name, b.name AS brand_name
                FROM ReceiptItem r JOIN Item i ON i.id=r.product_id JOIN Brand b ON b.id=i.brand_id
                WHERE r.receipt_id=?
            ''', (self.receipt['id'],)).fetchone()
            alias = db.execute("SELECT 1 FROM BrandAlias WHERE alias='Acme'").fetchone()
        self.assertEqual((product['name'], product['brand_name']), ('Acme Crisps', 'Acme Foods'))
        self.assertIsNone(alias)

    def test_final_brand_does_not_strip_a_candidate_from_the_product_name(self):
        self.engine.extract.return_value = document(
            'LIDL\n21/10/2026\nCroissant Chocolate\n£0.79\nTOTAL GBP £0.79'
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
            product = db.execute('''
                SELECT i.name FROM ReceiptItem r JOIN Item i ON i.id=r.product_id
                WHERE r.receipt_id=?
            ''', (self.receipt['id'],)).fetchone()
            alias = db.execute("SELECT 1 FROM BrandAlias WHERE alias='Croissant'").fetchone()
        self.assertEqual(product['name'], 'Croissant Chocolate')
        self.assertIsNone(alias)

    def test_unbranded_item_uses_editable_supermarket_default(self):
        self.engine.extract.return_value = document(
            'TESCO\n21/10/2026\nPlain Flour\n£1.20\nTOTAL GBP £1.20'
        )
        self.assertEqual(self.client.post(self.url).status_code, 200)
        item = self.client.get(f"/receipts/{self.receipt['id']}").json()['items'][0]
        self.assertIsNone(item['brand_id'])
        self.assertEqual((item['brand_name'], item['brand_source']), ('Tesco', 'supermarket'))
        self.assertEqual(self.client.post(f"/receipts/{self.receipt['id']}/verify", json={}).status_code, 200)

    def test_category_suggestion_can_be_overridden_before_verification(self):
        self.engine.extract.return_value = document(
            'TESCO\n21/10/2026\nBananas\n£1.20\nTOTAL GBP £1.20'
        )
        self.assertEqual(self.client.post(self.url).status_code, 200)
        item = self.client.get(f"/receipts/{self.receipt['id']}").json()['items'][0]
        self.assertEqual((item['category_name'], item['category_source']), ('Fruit & Vegetables', 'suggested'))
        with closing(connect(self.database_path)) as db:
            household_id = db.execute("SELECT id FROM categories WHERE name='Household'").fetchone()['id']
        item['category_id'] = household_id
        response = self.client.patch(f"/receipts/{self.receipt['id']}/review", json={'items': [item]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.post(f"/receipts/{self.receipt['id']}/verify", json={}).status_code, 200)
        with closing(connect(self.database_path)) as db:
            category = db.execute('''
                SELECT c.name FROM ReceiptItem r JOIN categories c ON c.id=r.category_id
                WHERE r.receipt_id=?
            ''', (self.receipt['id'],)).fetchone()
        self.assertEqual(category['name'], 'Household')

    def test_strawberry_flavour_is_not_suggested_as_fruit(self):
        self.engine.extract.return_value = document(
            'TESCO\n21/10/2026\nStrawberry Flavour Biscuits\n£1.20\nTOTAL GBP 1.20'
        )
        self.assertEqual(self.client.post(self.url).status_code, 200)
        item = self.client.get(f"/receipts/{self.receipt['id']}").json()['items'][0]
        self.assertEqual(item['category_name'], 'Snacks & Chocolates')

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
            self.assertEqual([item['original_pence'] for item in receipt['items']], [120, 230])


if __name__ == '__main__':
    unittest.main()

"""Parser regressions from saved OCR text and optional local image coverage."""

import json
from pathlib import Path
import unittest

from spending.receipt_parser import parse_receipt

ROOT = Path(__file__).resolve().parent.parent
IMAGE_DIR = ROOT / 'receipt-image'
RESULTS = Path(__file__).resolve().parent / 'fixtures' / 'receipt_image_ocr.json'


class ReceiptImageRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = json.loads(RESULTS.read_text(encoding='utf-8'))

    def test_every_receipt_image_has_a_saved_ocr_result(self):
        if not IMAGE_DIR.is_dir():
            self.skipTest('Local receipt-image directory is not included in the repository')
        images = {path.name for path in IMAGE_DIR.iterdir() if path.is_file()}
        self.assertEqual(set(self.results), images)

    def test_saved_ocr_results_keep_their_verified_metrics(self):
        for name, result in self.results.items():
            with self.subTest(image=name):
                parsed = parse_receipt(result['text'])
                summary = result['summary']
                gross = sum(item.original_pence for item in parsed.items)
                discount = sum(item.discount_pence for item in parsed.items)
                self.assertEqual(parsed.supermarket_name, summary['store'])
                self.assertEqual(parsed.purchase_date, summary['date'])
                self.assertEqual(len(parsed.items), summary['items'])
                self.assertEqual(gross, summary['gross_pence'])
                self.assertEqual(discount, summary['item_discount_pence'])
                self.assertEqual(parsed.receipt_discount_pence, summary['voucher_pence'])
                self.assertEqual(parsed.total_pence, summary['total_pence'])
                reconciles = (parsed.total_pence is not None and
                              gross - discount - parsed.receipt_discount_pence == parsed.total_pence)
                self.assertEqual(reconciles, summary['reconciles'])
                self.assertTrue(summary['reconciles'] or summary['points_only'])


if __name__ == '__main__':
    unittest.main()

"""Tests for the read-only Pandas export used by Power BI."""

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import pandas as pd

from analytics.export import export_verified_data
from spending.database import connect, initialize


class AnalyticsExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.database_path = root / 'spending.db'
        self.output_dir = root / 'analytics'
        initialize(self.database_path)
        with closing(connect(self.database_path)) as db, db:
            supermarket_id = db.execute("INSERT INTO Supermarket(name) VALUES ('Tesco')").lastrowid
            category_id = db.execute("SELECT id FROM categories WHERE name='Pantry'").fetchone()[0]
            item_id = db.execute("INSERT INTO Item(name, category_id) VALUES ('Rice', ?)", (category_id,)).lastrowid
            verified_id = db.execute(
                "INSERT INTO Receipt(supermarket_id, purchase_date, total_pence, voucher_pence, status) "
                "VALUES (?, '2026-10-20', 450, 50, 'verified')", (supermarket_id,)
            ).lastrowid
            db.execute(
                "INSERT INTO Receipt(supermarket_id, purchase_date, total_pence, status) "
                "VALUES (?, '2026-10-21', 999, 'needs_review')", (supermarket_id,)
            )
            db.execute(
                "INSERT INTO ReceiptItem(receipt_id, line_number, product_id, raw_description, "
                "original_pence, discount_pence) VALUES (?, 1, ?, 'Rice', 500, 50)",
                (verified_id, item_id),
            )

    def test_export_uses_verified_records_and_preserves_source_values(self):
        paths = export_verified_data(self.database_path, self.output_dir)
        self.assertEqual(set(paths), {
            'receipts', 'receipt_items', 'monthly_spending', 'category_spending', 'supermarket_spending',
        })
        receipts = pd.read_csv(paths['receipts'])
        items = pd.read_csv(paths['receipt_items'])
        monthly = pd.read_csv(paths['monthly_spending'])
        category = pd.read_csv(paths['category_spending'])
        self.assertEqual(receipts[['total_pence', 'voucher_pence']].iloc[0].tolist(), [450, 50])
        self.assertEqual(items[['original_pence', 'discount_pence', 'net_pence']].iloc[0].tolist(), [500, 50, 450])
        self.assertEqual(monthly[['receipt_count', 'total_pence']].iloc[0].tolist(), [1, 450])
        self.assertEqual(category[['category_name', 'total_pence']].iloc[0].tolist(), ['Pantry', 450])


if __name__ == '__main__':
    unittest.main()

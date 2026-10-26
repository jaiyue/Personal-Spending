import sqlite3
import tempfile
import unittest
from pathlib import Path

from spending.database import connect, initialize


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'spending.db'
        initialize(self.path)
        self.db = connect(self.path)
        self.db.execute("INSERT INTO Supermarket(id, name) VALUES (1, 'Example supermarket')")
        self.db.execute("INSERT INTO categories(id, name) VALUES (1, 'Food')")
        self.db.execute("INSERT INTO Item(id, name, category_id, pack_size, pack_unit) VALUES (1, 'Rice', 1, 500, 'g')")
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def receipt(self, receipt_id=1, total=300, currency='GBP', status='verified'):
        self.db.execute(
            "INSERT INTO Receipt(id, supermarket_id, purchase_date, total_minor, currency, status) VALUES (?, 1, '2026-10-20', ?, ?, ?)",
            (receipt_id, total, currency, status),
        )

    def item(self, receipt_id=1, item_id=1, total=300):
        self.db.execute(
            "INSERT INTO ReceiptItem(id, receipt_id, line_number, product_id, raw_description, line_total_minor) VALUES (?, ?, 1, 1, 'Rice', ?)",
            (item_id, receipt_id, total),
        )

    def test_initialize_is_repeatable(self):
        self.receipt()
        self.db.commit()
        self.assertIsNone(initialize(self.path))
        self.assertEqual(self.db.execute('SELECT count(*) FROM Receipt').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM schema_migrations').fetchone()[0], 1)

    def test_foreign_keys_and_deletion_protect_receipts(self):
        self.receipt()
        self.item()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('DELETE FROM Receipt WHERE id = 1')
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO ReceiptItem(receipt_id, line_number, raw_description, line_total_minor) VALUES (999, 1, 'Unknown', 10)")

    def test_amounts_dates_and_verification_are_validated(self):
        for date in ('2026-02-30', '2026-13-01', 'invalid'):
            with self.subTest(date=date), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute('INSERT INTO Receipt(purchase_date) VALUES (?)', (date,))
        for total in (-1, 1.25):
            with self.subTest(total=total), self.assertRaises(sqlite3.IntegrityError):
                self.receipt(total=total)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO Receipt(status) VALUES ('verified')")
        self.db.execute("INSERT INTO Receipt(status) VALUES ('needs_review')")

    def test_duplicate_file_and_receipt_line_rejected(self):
        self.receipt()
        self.item()
        with self.assertRaises(sqlite3.IntegrityError):
            self.item(item_id=2)
        digest = 'a' * 64
        self.db.execute('UPDATE Receipt SET file_sha256 = ? WHERE id = 1', (digest,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('INSERT INTO Receipt(file_sha256) VALUES (?)', (digest,))

    def test_corrections_cannot_link_different_receipts(self):
        self.receipt()
        self.item()
        self.receipt(receipt_id=2)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO correction_audit(receipt_id, receipt_item_id, field_name) VALUES (2, 1, 'quantity')")
        self.db.execute("INSERT INTO ocr_runs(id, receipt_id, engine) VALUES (1, 1, 'test')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO correction_audit(receipt_id, ocr_run_id, field_name) VALUES (2, 1, 'total_minor')")
        self.db.execute("INSERT INTO correction_audit(receipt_id, receipt_item_id, ocr_run_id, field_name, original_value, corrected_value) VALUES (1, 1, 1, 'quantity', '2', '1')")

    def test_analytics_separate_currency_and_exclude_unverified(self):
        self.receipt(total=300)
        self.item(total=100)
        self.db.execute("INSERT INTO ReceiptItem(receipt_id, line_number, product_id, raw_description, line_total_minor) VALUES (1, 2, 1, 'Rice', 200)")
        self.receipt(receipt_id=2, total=500, currency='EUR')
        self.receipt(receipt_id=3, total=999, status='needs_review')
        totals = dict(self.db.execute('SELECT currency, total_minor FROM v_monthly_spending'))
        self.assertEqual(totals, {'GBP': 300, 'EUR': 500})
        self.assertEqual(self.db.execute("SELECT total_minor FROM v_supermarket_spending WHERE currency='GBP'").fetchone()[0], 300)
        self.assertEqual(self.db.execute('SELECT total_minor FROM v_category_spending').fetchone()[0], 300)

    def test_reconciliation_and_budget(self):
        self.receipt(total=275)
        self.item(total=300)
        self.db.execute('UPDATE Receipt SET discount_minor=20, voucher_minor=10, adjustment_minor=5 WHERE id=1')
        self.assertEqual(self.db.execute('SELECT difference_minor FROM v_receipt_reconciliation').fetchone()[0], 0)
        self.db.execute("INSERT INTO budgets(month, amount_minor) VALUES ('2026-10', 1000)")
        self.db.execute("INSERT INTO budgets(month, category_id, amount_minor) VALUES ('2026-10', 1, 500)")
        self.assertEqual([tuple(r) for r in self.db.execute('SELECT actual_minor, remaining_minor FROM v_budget_vs_actual ORDER BY id')], [(275, 725), (300, 200)])
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO budgets(month, amount_minor) VALUES ('2026-10', 100)")

    def test_price_history_converts_units_and_keeps_snapshot(self):
        self.db.execute("INSERT INTO price_observations(product_id, supermarket_id, price_minor, pack_size, pack_unit, source_type, observed_at) VALUES (1, 1, 250, 500, 'g', 'manual', '2026-10-20T12:00:00Z')")
        self.db.execute('UPDATE Item SET pack_size = 1000 WHERE id=1')
        row = self.db.execute('SELECT unit_basis, unit_price_minor FROM v_product_price_history').fetchone()
        self.assertEqual(tuple(row), ('kg', 500.0))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO price_observations(product_id, supermarket_id, price_minor, source_type, observed_at) VALUES (1, 1, 250, 'receipt', '2026-10-20')")

    def test_shopping_list_cleanup(self):
        self.db.execute("INSERT INTO shopping_lists(id, name) VALUES (1, 'Weekly shop')")
        self.db.execute("INSERT INTO shopping_list_items(shopping_list_id, product_id, description) VALUES (1, 1, 'Rice')")
        self.db.execute('DELETE FROM shopping_lists WHERE id=1')
        self.assertEqual(self.db.execute('SELECT count(*) FROM shopping_list_items').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()

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
        self.product_id = 1000
        self.db.execute("INSERT INTO Supermarket(id, name) VALUES (1, 'Example supermarket')")
        self.category_id = self.db.execute(
            "SELECT id FROM categories WHERE name = 'Pantry'"
        ).fetchone()[0]
        self.db.execute(
            "INSERT INTO Item(id, name, category_id, pack_size, pack_unit) VALUES (?, 'Rice', ?, 500, 'g')",
            (self.product_id, self.category_id),
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def receipt(self, receipt_id=1, total=300, currency='GBP', status='verified'):
        self.db.execute(
            "INSERT INTO Receipt(id, supermarket_id, purchase_date, total_pence, currency, status) VALUES (?, 1, '2026-10-20', ?, ?, ?)",
            (receipt_id, total, currency, status),
        )

    def item(self, receipt_id=1, item_id=1, total=300):
        self.db.execute(
            "INSERT INTO ReceiptItem(id, receipt_id, line_number, product_id, raw_description, original_pence) VALUES (?, ?, 1, ?, 'Rice', ?)",
            (item_id, receipt_id, self.product_id, total),
        )

    def test_initialize_is_repeatable(self):
        self.receipt()
        self.db.commit()
        self.assertIsNone(initialize(self.path))
        self.assertEqual(self.db.execute('SELECT count(*) FROM Receipt').fetchone()[0], 1)
        tables = self.db.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        self.assertEqual(tables, 19)
        columns = {row['name'] for row in self.db.execute('PRAGMA table_info(ReceiptItem)')}
        self.assertNotIn('after_discount_pence', columns)

    def test_brand_is_unique_and_items_reference_it(self):
        columns = {row['name'] for row in self.db.execute('PRAGMA table_info(Item)')}
        self.assertNotIn('brand', columns)
        self.assertIn('brand_id', columns)
        brand_id = self.db.execute("SELECT id FROM Brand WHERE name = 'Hovis'").fetchone()[0]
        self.db.execute("UPDATE Item SET brand_id=? WHERE id=?", (brand_id, self.product_id))
        self.assertEqual(self.db.execute('SELECT brand_id FROM Item WHERE id=?', (self.product_id,)).fetchone()[0], brand_id)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO Brand(name) VALUES ('hovis')")

    def test_common_brands_are_seeded(self):
        brands = {row[0] for row in self.db.execute('SELECT name FROM Brand')}
        self.assertTrue({'Hovis', 'Tesco', 'Lidl', 'B&M', 'Heinz', 'Lurpak'} <= brands)

    def test_grocery_merchants_have_a_default_expense_category(self):
        rows = dict(self.db.execute('''
            SELECT m.merchant_name, e.name FROM MerchantExpenseCategory m
            JOIN ExpenseCategory e ON e.id=m.expense_category_id
        '''))
        self.assertEqual(rows['Tesco'], 'Groceries')
        self.assertEqual(rows["Sainsbury's"], 'Groceries')

    def test_brand_aliases_reference_canonical_brands(self):
        brand = self.db.execute('''
            SELECT b.name FROM BrandAlias a JOIN Brand b ON b.id=a.brand_id
            WHERE a.alias='Coca Cola' COLLATE NOCASE
        ''').fetchone()
        self.assertEqual(brand['name'], 'Coca-Cola')
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO BrandAlias(brand_id, alias) VALUES (999, 'Missing')")

    def test_foreign_keys_and_deletion_protect_receipts(self):
        self.receipt()
        self.item()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('DELETE FROM Receipt WHERE id = 1')
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO ReceiptItem(receipt_id, line_number, raw_description, original_pence) VALUES (999, 1, 'Unknown', 10)")

    def test_item_discounts_keep_reasons_and_share_promotion_groups(self):
        self.receipt()
        self.item()
        group_id = self.db.execute(
            "INSERT INTO PromotionGroup(receipt_id, sequence, marker_text, advertised_quantity, advertised_price_pence) "
            "VALUES (1, 1, '3 for £2.00', 3, 200)"
        ).lastrowid
        self.db.execute(
            'INSERT INTO ReceiptItemPromotionGroup(promotion_group_id, receipt_item_id, receipt_id) VALUES (?, 1, 1)',
            (group_id,),
        )
        self.db.execute(
            "INSERT INTO ItemDiscount(receipt_item_id, receipt_id, promotion_group_id, sequence, amount_pence, reason, source_text) "
            "VALUES (1, 1, ?, 1, 20, 'Clubcard', '-£0.20')",
            (group_id,),
        )
        row = self.db.execute('''
            SELECT d.amount_pence, d.reason, p.marker_text FROM ItemDiscount d
            JOIN PromotionGroup p ON p.id=d.promotion_group_id
        ''').fetchone()
        self.assertEqual(tuple(row), (20, 'Clubcard', '3 for £2.00'))

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
            self.db.execute("INSERT INTO correction_audit(receipt_id, ocr_run_id, field_name) VALUES (2, 1, 'total_pence')")
        self.db.execute("INSERT INTO correction_audit(receipt_id, receipt_item_id, ocr_run_id, field_name, original_value, corrected_value) VALUES (1, 1, 1, 'quantity', '2', '1')")

    def test_analytics_separate_currency_and_exclude_unverified(self):
        self.receipt(total=300)
        self.item(total=100)
        self.db.execute("INSERT INTO ReceiptItem(receipt_id, line_number, product_id, raw_description, original_pence) VALUES (1, 2, ?, 'Rice', 200)", (self.product_id,))
        self.receipt(receipt_id=2, total=500, currency='EUR')
        self.receipt(receipt_id=3, total=999, status='needs_review')
        totals = dict(self.db.execute('SELECT currency, total_pence FROM v_monthly_spending'))
        self.assertEqual(totals, {'GBP': 300, 'EUR': 500})
        self.assertEqual(self.db.execute("SELECT total_pence FROM v_supermarket_spending WHERE currency='GBP'").fetchone()[0], 300)
        self.assertEqual(self.db.execute('SELECT total_pence FROM v_category_spending').fetchone()[0], 300)

    def test_reconciliation_and_budget(self):
        self.receipt(total=275)
        self.item(total=300)
        self.db.execute('UPDATE ReceiptItem SET discount_pence=20 WHERE id=1')
        self.db.execute('UPDATE Receipt SET discount_pence=20, voucher_pence=10, adjustment_pence=5 WHERE id=1')
        self.assertEqual(self.db.execute('SELECT difference_pence FROM v_receipt_reconciliation').fetchone()[0], 0)
        self.db.execute("INSERT INTO budgets(month, amount_pence) VALUES ('2026-10', 1000)")
        self.db.execute(
            "INSERT INTO budgets(month, category_id, amount_pence) VALUES ('2026-10', ?, 500)",
            (self.category_id,),
        )
        self.assertEqual([tuple(r) for r in self.db.execute('SELECT actual_pence, remaining_pence FROM v_budget_vs_actual ORDER BY id')], [(275, 725), (280, 220)])
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO budgets(month, amount_pence) VALUES ('2026-10', 100)")

    def test_price_history_converts_units_and_keeps_snapshot(self):
        self.db.execute("INSERT INTO price_observations(product_id, supermarket_id, price_pence, pack_size, pack_unit, source_type, observed_at) VALUES (?, 1, 250, 500, 'g', 'manual', '2026-10-20T12:00:00Z')", (self.product_id,))
        self.db.execute('UPDATE Item SET pack_size = 1000 WHERE id=?', (self.product_id,))
        row = self.db.execute('SELECT unit_basis, unit_price_pence FROM v_product_price_history').fetchone()
        self.assertEqual(tuple(row), ('kg', 500.0))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO price_observations(product_id, supermarket_id, price_pence, source_type, observed_at) VALUES (?, 1, 250, 'receipt', '2026-10-20')", (self.product_id,))

    def test_shopping_list_cleanup(self):
        self.db.execute("INSERT INTO shopping_lists(id, name) VALUES (1, 'Weekly shop')")
        self.db.execute("INSERT INTO shopping_list_items(shopping_list_id, product_id, description) VALUES (1, ?, 'Rice')", (self.product_id,))
        self.db.execute('DELETE FROM shopping_lists WHERE id=1')
        self.assertEqual(self.db.execute('SELECT count(*) FROM shopping_list_items').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()

import sqlite3
from contextlib import closing
import hashlib
import tempfile
import unittest
from pathlib import Path

from spending.database import MIGRATIONS, connect, initialize


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
        self.assertEqual(self.db.execute('SELECT count(*) FROM schema_migrations').fetchone()[0], 2)

    def test_backup_preserves_legacy_data(self):
        path = Path(self.directory.name) / 'legacy.db'
        with closing(sqlite3.connect(path)) as old, old:
            old.execute('CREATE TABLE Receipt (ReceiptID INTEGER PRIMARY KEY, TotalPrice INTEGER)')
            old.execute('INSERT INTO Receipt VALUES (1, 123)')
        backup = initialize(path)
        self.assertTrue(backup.exists())
        for database in (path, backup):
            with closing(sqlite3.connect(database)) as db:
                table = 'legacy_Receipt' if database == path else 'Receipt'
                self.assertEqual(db.execute(f'SELECT TotalPrice FROM {table}').fetchone()[0], 123)

    def test_failed_migration_rolls_back_ddl(self):
        path = Path(self.directory.name) / 'collision.db'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE products (id INTEGER)')
        with self.assertRaises(sqlite3.OperationalError):
            initialize(path)
        with closing(sqlite3.connect(path)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(tables, {'products'})

    def test_upgrade_reuses_original_names_and_preserves_both_layouts(self):
        path = Path(self.directory.name) / 'upgrade.db'
        original = MIGRATIONS / '001_initial.sql'
        sql = original.read_text()
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript('''
                PRAGMA foreign_keys = ON;
                CREATE TABLE Supermarket (SupermarketID INTEGER PRIMARY KEY, Name TEXT);
                CREATE TABLE Item (ItemID INTEGER PRIMARY KEY, Name TEXT);
                CREATE TABLE Receipt (ReceiptID INTEGER PRIMARY KEY, SupermarketID INTEGER
                    REFERENCES Supermarket(SupermarketID), TotalPrice INTEGER);
                CREATE TABLE ReceiptItem (ReceiptItemID INTEGER PRIMARY KEY,
                    ReceiptID INTEGER REFERENCES Receipt(ReceiptID),
                    ItemID INTEGER REFERENCES Item(ItemID));
                INSERT INTO Supermarket VALUES (10, 'Original supermarket');
                INSERT INTO Item VALUES (20, 'Original item');
                INSERT INTO Receipt VALUES (30, 10, 123);
                INSERT INTO ReceiptItem VALUES (40, 30, 20);
            ''')
            db.executescript(sql)
            db.execute('CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, checksum TEXT, applied_at TEXT)')
            db.execute('INSERT INTO schema_migrations(version, checksum) VALUES (?, ?)',
                       (original.name, hashlib.sha256(sql.encode()).hexdigest()))
            db.execute("INSERT INTO retailers(id, name) VALUES (1, 'New supermarket')")
            db.execute("INSERT INTO products(id, name) VALUES (1, 'New item')")
            db.execute("INSERT INTO receipts(id, retailer_id, purchase_date, total_minor, status) VALUES (1, 1, '2026-10-20', 300, 'verified')")
            db.execute("INSERT INTO receipt_items(id, receipt_id, product_id, line_number, raw_description, line_total_minor) VALUES (1, 1, 1, 1, 'New item', 300)")
        self.assertTrue(initialize(path).exists())
        db = connect(path)
        try:
            self.assertEqual(db.execute('SELECT TotalPrice FROM legacy_Receipt').fetchone()[0], 123)
            self.assertEqual(tuple(db.execute('SELECT ReceiptID, ItemID FROM legacy_ReceiptItem').fetchone()), (30, 20))
            self.assertEqual(tuple(db.execute('SELECT supermarket_id, total_minor FROM Receipt').fetchone()), (1, 300))
            self.assertEqual(db.execute('SELECT product_id FROM ReceiptItem').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT name FROM Item').fetchone()[0], 'New item')
            self.assertEqual(db.execute('SELECT total_minor FROM v_supermarket_spending').fetchone()[0], 300)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({'Supermarket', 'Item', 'Receipt', 'ReceiptItem'} <= tables)
            self.assertFalse({'retailers', 'products', 'receipts', 'receipt_items'} & tables)
        finally:
            db.close()
        self.assertIsNone(initialize(path))

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
        self.db.execute('UPDATE Receipt SET discount_minor=30, adjustment_minor=5 WHERE id=1')
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

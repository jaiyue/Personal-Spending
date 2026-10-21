# Database Tests

The 12 tests in [test_database.py](test_database.py) check the implemented SQLite
schema, migrations, constraints, and analytical views. They use Python's built-in
`unittest`, with no additional dependencies.

The suite covers the **grocery module**. Synthetic rice purchases represent
grocery items; category-based totals and budgets refer to grocery product groups,
and overall totals/budgets refer to grocery spending only. No other expense
types or expense-type selection workflow are implemented. Source, price, and
quality issue types describe records within grocery.

## Running the tests

Run all database tests from the repository root:

```bash
python -m unittest discover -s tests -v
```

To run one test:

```bash
python -m unittest discover -s tests -v -k test_reconciliation_and_budget
```

Each test creates its own temporary database, initialises the real SQL schema,
and inserts synthetic retailer, category, and product records. `tearDown` closes
the connection and removes temporary files. The tests do not read or modify
`data/spending.db` or real receipts. The `receipt()` and `item()` helper methods
create sample records; they are not separate tests.

## Purpose of each test

| Test | Scenario and expected result | Why it matters |
|---|---|---|
| `test_initialize_is_repeatable` | Initialise an existing database again after saving a receipt. The receipt remains, there are two migration records, and no new backup is needed when nothing changes. | Allows repeated setup without losing data or applying a migration twice. |
| `test_backup_preserves_legacy_data` | Start with a legacy `Receipt` table containing a record. Initialise the new schema and verify the record in the updated database's `legacy_Receipt` table and the backup's original `Receipt` table. | Protects existing records while reusing their original table names for the active schema. |
| `test_upgrade_reuses_original_names_and_preserves_both_layouts` | Upgrade a database containing migration 001 records and all four original tables with linked data. Verify the active names, archived records, foreign keys, new records, supermarket spending view, backup, and repeatable setup. | Confirms the naming migration preserves both datasets and their relationships. |
| `test_failed_migration_rolls_back_ddl` | Create a conflicting `Item` table so the migration fails. Only the original table remains; newly created tables and migration metadata are rolled back. | Prevents a failed migration from leaving a partially installed schema. |
| `test_foreign_keys_and_deletion_protect_receipts` | Try deleting a receipt that has items and inserting an item referencing a nonexistent receipt. Both operations raise `sqlite3.IntegrityError`. | Prevents orphaned receipt items and accidental removal of purchase history. |
| `test_amounts_dates_and_verification_are_validated` | Reject impossible/malformed dates, negative totals, fractional minor-unit totals, and a verified receipt missing required fields. Accept an incomplete receipt marked `needs_review`. | Keeps invalid records out while allowing incomplete OCR output to await review. |
| `test_duplicate_file_and_receipt_line_rejected` | Insert a second item with the same receipt/line number, then another receipt with the same SHA-256 file hash. Both are rejected. | Prevents duplicate lines and ingestion of identical receipt files. |
| `test_corrections_cannot_link_different_receipts` | Attempt to link a correction to another receipt's item or OCR run. Both fail; a correction whose receipt, item, and OCR run agree is accepted. | Keeps correction history attached to the correct source receipt. |
| `test_analytics_separate_currency_and_exclude_unverified` | Create GBP and EUR receipts, an unverified receipt, and multiple lines on one verified receipt. Monthly totals remain separate by currency, unverified spending is excluded, and retailer/category totals avoid double counting. | Prevents misleading spending reports caused by currency mixing, review status, or joins. |
| `test_reconciliation_and_budget` | Reconcile a 300-minor-unit line total with a 30-unit receipt discount and a +5 adjustment against a 275-unit receipt total. Check overall/category actuals and remaining budgets; reject a duplicate overall monthly budget. | Verifies receipt accounting and distinguishes receipt-level spending from category-level line spending. |
| `test_price_history_converts_units_and_keeps_snapshot` | A 500 g package costing 250 pence produces 500 pence/kg. Changing the product catalogue size does not change the observation's historical unit price. Reject a receipt-sourced price without a receipt item. | Keeps historical comparisons stable and enforces the minimum source reference for receipt prices. |
| `test_shopping_list_cleanup` | Delete a shopping list containing an item and verify that its list items are removed automatically. | Ensures list deletion does not leave unused list-item records. |

## Coverage and limits

These are database integration tests using synthetic records. They cover selected
successful and rejected operations, rather than every field constraint or business
rule. The last local run passed all 12 tests. GitHub Actions is configured in
[database.yml](../.github/workflows/database.yml) to run them on pushes and pull
requests; a successful remote run has not been verified here.

OCR recognition accuracy, upload handling, API routes, mobile/desktop workflows,
authentication, and Power BI dashboards are not implemented or tested yet.
For storage rules and responsibilities of the future application, see the
[database guide](../docs/database.md).

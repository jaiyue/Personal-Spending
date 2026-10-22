# Local Data and Database Structure

`spending.db` is the local SQLite database. Initialise it from the project root:

```bash
python -m spending.database
```

The FastAPI backend also initialises this database on startup. API-uploaded
grocery documents are stored in `data/uploads/` by default; their `Receipt.source_path`
is a generated filename relative to the configured upload directory. Files are
deduplicated by SHA-256 and create a `pending` receipt awaiting OCR. See the
[API guide](../docs/api.md) for configuration and endpoints.

Local OCR is available through `POST /receipts/{receipt_id}/ocr`. It stores a
JSON document in `ocr_runs.raw_output` with extracted text, per-page source and
confidence, provisional fields/items and review warnings. Parsed values populate
`Receipt`/`ReceiptItem` with `needs_review`; product/category matches remain null.
No table names or schema fields were changed to add OCR. See the
[OCR guide](../docs/ocr.md) for recognition, retry and review rules.

Keep receipts, database files and timestamped `.bak` backups out of version
control. `.gitignore` excludes local data files, and `spending.db` has been
removed from Git tracking while keeping the local file. Earlier commits still
contain the previously tracked database; untracking does not rewrite Git history.

See [the database guide](../docs/database.md) for tables, migrations, validation
rules and analytical views.

## Schema overview

This database is dedicated to **grocery**. All active receipt, item, price,
quality-note, shopping-list, and budget records belong to this module. Grocery
is the module's implicit scope, so no general expense-type table or selector
is needed. Other personal expense types are outside this schema's current scope.

`categories` describes grocery product groups (for example, produce, dairy,
and grains), not domains such as transport or rent. A null `budgets.category_id`
means the overall **grocery** budget. All spending views report grocery purchases.

The existing `_type` fields describe grocery record details, not expense types:

| Field | Meaning | Allowed values |
|---|---|---|
| `Receipt.source_type` | How a grocery receipt was entered | `upload`, `camera`, `manual` |
| `price_observations.source_type` | Source of a grocery price | `receipt`, `online`, `manual` |
| `price_observations.price_type` | Price condition | `regular`, `promotion`, `loyalty` |
| `quality_notes.issue_type` | Grocery product quality issue | `packaging`, `spoilage`, `expiry`, `other` |

The implemented schema contains 12 business tables and the `schema_migrations`
metadata table. The field lists below reflect [001_initial.sql](../sql/001_initial.sql)
followed by [002_original_table_names.sql](../sql/002_original_table_names.sql),
and the migration metadata definition in [database.py](../spending/database.py).

Existing table names are reused: `retailers` becomes `Supermarket`, `products`
becomes `Item`, `receipts` becomes `Receipt`, and `receipt_items` becomes
`ReceiptItem`. Related columns use `supermarket_id`, and spending by store is
available through `v_supermarket_spending`. The extended schema keeps its
`id`, `product_id`, and `receipt_id` field conventions; this migration restores
table names rather than the old column layout.

Notation: `*` means **main / primary key (PK)**; `-` means **foreign key (FK)**.
Unmarked fields are ordinary columns. `->` identifies the referenced table and
column. A foreign key can be nullable; see the SQL for exact types, defaults,
and constraints.

## Tables and fields

```text
Supermarket Table: Retailer and store details
  * id (main)
    name, location, store_format

categories Table: Grocery product groups
  * id (main)
    name

Item Table: Standardised product catalogue
  * id (main)
  - category_id (foreign) -> categories.id
    name, brand, barcode, pack_size, pack_unit

Receipt Table: Receipt metadata, amounts, upload source and review status
  * id (main)
  - supermarket_id (foreign) -> Supermarket.id
    purchase_date, currency, total_minor, discount_minor, adjustment_minor
    source_path, file_sha256, source_type, status, created_at

ReceiptItem Table: Purchased lines and matched products
  * id (main)
  - receipt_id (foreign) -> Receipt.id
  - product_id (foreign) -> Item.id
  - category_id (foreign) -> categories.id
    line_number, raw_description, quantity, unit_price_minor
    discount_minor, line_total_minor

ocr_runs Table: OCR execution and original results
  * id (main)
  - receipt_id (foreign) -> Receipt.id
    engine, engine_version, status, raw_output, confidence
    error_message, started_at, completed_at

correction_audit Table: Field changes and correction history
  * id (main)
  - receipt_id (foreign) -> Receipt.id
  - (receipt_item_id, receipt_id) (foreign) -> ReceiptItem.(id, receipt_id)
  - (ocr_run_id, receipt_id) (foreign) -> ocr_runs.(id, receipt_id)
    field_name, original_value, corrected_value, corrected_by, corrected_at

price_observations Table: Historical package prices and source details
  * id (main)
  - product_id (foreign) -> Item.id
  - supermarket_id (foreign) -> Supermarket.id
  - receipt_item_id (foreign) -> ReceiptItem.id
    price_minor, currency, pack_size, pack_unit, price_type
    source_type, source_url, observed_at

quality_notes Table: Product issues and purchase notes
  * id (main)
  - product_id (foreign) -> Item.id
  - receipt_id (foreign) -> Receipt.id
  - (receipt_item_id, receipt_id) (foreign) -> ReceiptItem.(id, receipt_id)
    issue_type, note, created_at

shopping_lists Table: Shopping list names and lifecycle
  * id (main)
    name, status, created_at

shopping_list_items Table: Products/items to buy
  * id (main)
  - shopping_list_id (foreign) -> shopping_lists.id
  - product_id (foreign) -> Item.id
    description, quantity, purchased

budgets Table: Overall grocery or grocery-category monthly budgets
  * id (main)
  - category_id (foreign) -> categories.id
    month, currency, amount_minor

schema_migrations Table: Applied schema versions (technical metadata)
  * version (main)
    checksum, applied_at
```

The composite foreign keys in `correction_audit` and `quality_notes` ensure that
an item or OCR run belongs to the referenced receipt. A null `budgets.category_id`
means an overall monthly grocery budget.

## Analytical views (`v_`)

Views are saved SQL queries derived from tables; they do not store independent
copies of the data. The `v_` prefix distinguishes them from tables.

| View | Purpose | Main output fields |
|---|---|---|
| `v_monthly_spending` | Verified spending by month and currency | `month`, `currency`, `receipt_count`, `total_minor` |
| `v_supermarket_spending` | Verified spending by month, currency and retailer | `month`, `currency`, `supermarket_id`, `supermarket_name`, `receipt_count`, `total_minor` |
| `v_category_spending` | Verified item spending by month, currency and category | `month`, `currency`, `category_id`, `category_name`, `total_minor` |
| `v_receipt_reconciliation` | Compare receipt totals with line sums, discounts and adjustments | `receipt_id`, `currency`, `status`, `total_minor`, `item_count`, `items_total_minor`, `expected_total_minor`, `difference_minor` |
| `v_product_price_history` | Package-price history with normalised unit prices | All `price_observations` fields, plus `product_name`, `supermarket_name`, `unit_basis`, `unit_price_minor` |
| `v_budget_vs_actual` | Monthly budget, actual spending and remaining amount | All `budgets` fields, plus `actual_minor`, `remaining_minor` |

## Constraints, indexes and legacy tables

- `_minor` monetary amounts use integer minor units (for example, pence for GBP).
  Spending views separate currencies and include only verified grocery receipts.
- Unique constraints prevent duplicate file hashes, receipt line numbers,
  retailer name/location pairs, category names, and non-null product barcodes.
  Partial unique indexes prevent duplicate overall/category monthly budgets.
- `CHECK` constraints validate dates, amounts, positive quantities and pack
  sizes, status values, and required fields for verified Receipt.
- Indexes support receipt date/status queries, product/category lookups,
  receipt-linked records, price history, and shopping-list items.
- Historical receipt references use restrictive deletion rules. Shopping-list
  items are deleted automatically when their parent list is deleted.
- Original layouts and records are preserved as `legacy_Item`, `legacy_Receipt`,
  `legacy_Supermarket`, and `legacy_ReceiptItem` when present. Their foreign keys
  are updated to reference the archived tables. They are excluded from the new
  views and are not created in a fresh database. Importing their data remains
  pending confirmation of the original units and currency. The active schema
  uses `Item`, `Receipt`, `Supermarket`, and `ReceiptItem`.

See the [project README](../README.md) for current progress and the
[test guide](../tests/README.md) for database test coverage.

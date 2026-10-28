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
`PATCH /receipts/{receipt_id}/review` records manual before/after values in
`correction_audit`, and `POST /receipts/{receipt_id}/verify` includes a reconciled
receipt in spending views. No table names or schema fields were changed to add OCR. See the
[OCR guide](../docs/ocr.md) for recognition, retry and review rules.

Keep receipts, database files and timestamped `.bak` backups out of version
control. `.gitignore` excludes local data files, and `spending.db` has been
removed from Git tracking while keeping the local file. Earlier commits still
contain the previously tracked database; untracking does not rewrite Git history.

See [the database guide](../docs/database.md) for tables, setup, validation
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

The implemented schema contains 14 business tables. New databases are created
directly from the consolidated [schema.sql](../sql/schema.sql). During
development, structural changes are applied by rebuilding the local database.

The canonical schema uses `Supermarket`, `Item`, `Receipt`, and `ReceiptItem`.
Related columns use `supermarket_id`, and spending by store is available through
`v_supermarket_spending`. The extended schema keeps its `id`, `product_id`, and
`receipt_id` field conventions.

Notation: `*` means **main / primary key (PK)**; `-` means **foreign key (FK)**.
Unmarked fields are ordinary columns. `->` identifies the referenced table and
column. A foreign key can be nullable; see the SQL for exact types, defaults,
and constraints.

## Tables and fields

```text
Supermarket Table: Retailer and store details
  * id (main)
    name, location, store_format

Brand Table: Normalised manufacturer or supermarket own-brand name (common UK brands are seeded)
  * id (main)
    name

BrandAlias Table: Alternate printed names and OCR spellings for a canonical brand
  * id (main)
  - brand_id (foreign) -> Brand.id
    alias

categories Table: Grocery product groups
  * id (main)
    name

Item Table: Standardised product catalogue
  * id (main)
  - category_id (foreign) -> categories.id
  - brand_id (foreign) -> Brand.id
    name, barcode, pack_size, pack_unit

Receipt Table: Receipt metadata, amounts, upload source and review status
  * id (main)
  - supermarket_id (foreign) -> Supermarket.id
    purchase_date, currency, total_pence, discount_pence, voucher_pence, adjustment_pence
    source_path, file_sha256, source_type, status, created_at

`Receipt.discount_pence` preserves an explicit OCR summary such as `TOTAL
SAVINGS`; it is not calculated by adding the item discounts.

ReceiptItem Table: Purchased lines and matched products
  * id (main)
  - receipt_id (foreign) -> Receipt.id
  - product_id (foreign) -> Item.id
  - category_id (foreign) -> categories.id
    line_number, raw_description, quantity, unit_price_pence
    discount_pence, original_pence

`unit_price_pence`, `discount_pence`, and `original_pence` preserve individual
amounts shown by OCR or confirmed during manual review. They are never filled
with an inferred, combined, or reverse-calculated amount. Derived amounts such
as the price after discount are calculated only in queries and validation.

Before verification, each OCR item is checked against canonical `Brand.name`
values and `BrandAlias.alias` values. A known match returns its `brand_id`. An
unknown leading brand is shown as an editable suggestion; when no reliable
brand prefix exists, the receipt supermarket is the editable default. Both
cases remain editable until review. Clicking Verify confirms the current input,
creates or reuses that brand, and stores its ID on `Item`. OCR candidates are
review suggestions only; they are not stored as brands or aliases.

Verified `Item.name` stores only the product portion, with the brand prefix
removed. Later OCR lines are also matched against existing item names to
standardise the product portion. An item-name match never supplies a brand:
the brand must appear on the new receipt, be suggested from its leading text,
or use the editable supermarket default.

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
    price_pence, currency, pack_size, pack_unit, price_type
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
    month, currency, amount_pence

```

The composite foreign keys in `correction_audit` and `quality_notes` ensure that
an item or OCR run belongs to the referenced receipt. A null `budgets.category_id`
means an overall monthly grocery budget.

## Analytical views (`v_`)

Views are saved SQL queries derived from tables; they do not store independent
copies of the data. The `v_` prefix distinguishes them from tables.

| View | Purpose | Main output fields |
|---|---|---|
| `v_monthly_spending` | Verified spending by month and currency | `month`, `currency`, `receipt_count`, `total_pence` |
| `v_supermarket_spending` | Verified spending by month, currency and retailer | `month`, `currency`, `supermarket_id`, `supermarket_name`, `receipt_count`, `total_pence` |
| `v_category_spending` | Verified item spending by month, currency and category | `month`, `currency`, `category_id`, `category_name`, `total_pence` |
| `v_receipt_reconciliation` | Compare receipt totals with line sums, discounts, vouchers and adjustments | `receipt_id`, `currency`, `status`, `total_pence`, `item_count`, `items_total_pence`, `expected_total_pence`, `difference_pence` |
| `v_product_price_history` | Package-price history with normalised unit prices | All `price_observations` fields, plus `product_name`, `supermarket_name`, `unit_basis`, `unit_price_pence` |
| `v_budget_vs_actual` | Monthly budget, actual spending and remaining amount | All `budgets` fields, plus `actual_pence`, `remaining_pence` |

## Constraints, indexes and legacy tables

- `_pence` monetary amounts use integer pence (for example, pence for GBP).
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
- The active schema uses `Item`, `Receipt`, `Supermarket`, and `ReceiptItem`.

See the [project README](../README.md) for current progress and the
[test guide](../tests/README.md) for database test coverage.

# Database and API Tests

The 11 tests in [test_database.py](test_database.py) check the implemented SQLite
schema, constraints, and analytical views. They use Python's built-in
`unittest`, with no additional dependencies.

The additional 21 tests in [test_api.py](test_api.py) exercise the FastAPI backend
using TestClient, a temporary SQLite database, a temporary upload directory,
and synthetic PNG/JPEG/PDF documents. [test_ocr.py](test_ocr.py) adds 38 parser,
engine and OCR API tests. The full suite contains **70 tests**.
API tests require the dependencies in `requirements-dev.txt` (including httpx2,
which is used by the installed Starlette TestClient).

The suite covers the **grocery module**. Synthetic rice purchases represent
grocery items; category-based totals and budgets refer to grocery product groups,
and overall totals/budgets refer to grocery spending only. No other expense
types or expense-type selection workflow are implemented. Source, price, and
quality issue types describe records within grocery.

## Running the tests

Install dependencies and run all tests from the repository root:

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Run only one suite:

```bash
python -m unittest discover -s tests -p 'test_database.py' -v
python -m unittest discover -s tests -p 'test_api.py' -v
python -m unittest discover -s tests -p 'test_ocr.py' -v
```

Three OCR tests invoke RapidOCR (image, scanned PDF and HTTP-to-database). They
run when the Python dependencies are installed. RapidOCR obtains local model
files on its first image-recognition request. See the [OCR guide](../docs/ocr.md)
for setup. Other OCR tests use synthetic text or injected engine results.

To run one test:

```bash
python -m unittest discover -s tests -v -k test_reconciliation_and_budget
```

Each test creates its own temporary database, initialises the real SQL schema,
and inserts synthetic retailer, category, and product records. `tearDown` closes
the connection and removes temporary files. The tests do not read or modify
`data/spending.db` or real receipts. The `receipt()` and `item()` helper methods
create sample records; they are not separate tests.

## Purpose of each database test

| Test | Scenario and expected result | Why it matters |
|---|---|---|
| `test_initialize_is_repeatable` | Initialise an existing database again after saving a receipt. The receipt remains, the canonical schema record remains unchanged. | Allows repeated setup without losing data or applying a migration twice. |
| `test_brand_is_unique_and_items_reference_it` | Link an Item to the seeded `Hovis` brand, then reject a case-insensitive duplicate brand. | Keeps brand analysis consistent across supermarket items. |
| `test_common_brands_are_seeded` | Create a fresh database and confirm that common manufacturer and supermarket brands, including Hovis, Tesco, Lidl, Heinz and Lurpak, are present. | Makes the brand catalogue available immediately on new and existing databases. |
| `test_foreign_keys_and_deletion_protect_receipts` | Try deleting a receipt that has items and inserting an item referencing a nonexistent receipt. Both operations raise `sqlite3.IntegrityError`. | Prevents orphaned receipt items and accidental removal of purchase history. |
| `test_amounts_dates_and_verification_are_validated` | Reject impossible/malformed dates, negative totals, fractional minor-unit totals, and a verified receipt missing required fields. Accept an incomplete receipt marked `needs_review`. | Keeps invalid records out while allowing incomplete OCR output to await review. |
| `test_duplicate_file_and_receipt_line_rejected` | Insert a second item with the same receipt/line number, then another receipt with the same SHA-256 file hash. Both are rejected. | Prevents duplicate lines and ingestion of identical receipt files. |
| `test_corrections_cannot_link_different_receipts` | Attempt to link a correction to another receipt's item or OCR run. Both fail; a correction whose receipt, item, and OCR run agree is accepted. | Keeps correction history attached to the correct source receipt. |
| `test_analytics_separate_currency_and_exclude_unverified` | Create GBP and EUR receipts, an unverified receipt, and multiple lines on one verified receipt. Monthly totals remain separate by currency, unverified spending is excluded, and retailer/category totals avoid double counting. | Prevents misleading spending reports caused by currency mixing, review status, or joins. |
| `test_reconciliation_and_budget` | Reconcile a 300-minor-unit line total with a 30-unit receipt discount and a +5 adjustment against a 275-unit receipt total. Check overall/category actuals and remaining budgets; reject a duplicate overall monthly budget. | Verifies receipt accounting and distinguishes receipt-level spending from category-level line spending. |
| `test_price_history_converts_units_and_keeps_snapshot` | A 500 g package costing 250 pence produces 500 pence/kg. Changing the product catalogue size does not change the observation's historical unit price. Reject a receipt-sourced price without a receipt item. | Keeps historical comparisons stable and enforces the minimum source reference for receipt prices. |
| `test_shopping_list_cleanup` | Delete a shopping list containing an item and verify that its list items are removed automatically. | Ensures list deletion does not leave unused list-item records. |

## Purpose of each API test

Every test creates its own app through `create_app`, starts its lifespan using
TestClient, and cleans up the client before removing temporary files. All requests
are in-process; no running server or real grocery documents are required.

| Test | Scenario and expected result | Why it matters |
|---|---|---|
| `test_startup_and_health` | Startup creates the temporary schema/upload directory; `/health` returns 200 and an available database. | Checks application setup and database connectivity. |
| `test_desktop_development_origin_is_allowed` | The Vite development origin receives the expected CORS preflight response. | Lets the separate desktop page call the local API from its browser origin. |
| `test_factory_defers_filesystem_changes_until_startup` | Constructing an app leaves the filesystem unchanged; a nonpositive upload limit raises an error. | Avoids import-time data changes and invalid configuration. |
| `test_upload_persists_original_bytes_hash_and_pending_record` | Upload a PNG with path components in its client filename. Verify original bytes, generated storage filename, SHA-256, pending record and Location header; no OCR run or spending total is created. | Proves the upload-to-database workflow and safe filename handling. |
| `test_accepts_png_jpeg_and_pdf` | Upload real synthetic PNG, JPEG and PDF documents, including uppercase extensions. Each returns 201 with the appropriate stored suffix. | Checks all supported document formats. |
| `test_generic_binary_mime_is_validated_by_contents` | A valid PNG sent as `application/octet-stream` is accepted. | Allows generic upload MIME metadata while still validating contents. |
| `test_duplicate_bytes_rejected_even_with_different_filename` | Re-upload identical bytes under a different name; return 409 and the original ID, with one record and one file remaining. | Prevents duplicate ingestion based on file content. |
| `test_delete_receipt_removes_file_and_derived_records` | Delete a receipt with OCR, item and audit records; its database rows and uploaded file are removed. | Ensures a user can remove an unwanted receipt without orphaned derived data. |
| `test_processing_receipt_cannot_be_deleted` | Reject deletion while OCR is processing and retain the uploaded file. | Avoids deleting a record while its recognition request is active. |
| `test_rejects_unsupported_extensions_and_mime_mismatch` | Reject an unsupported extension or a mismatched declared MIME type with 415; leave no rows/files. | Enforces allowed upload metadata. |
| `test_rejects_corrupt_or_mislabeled_documents` | Reject disguised/truncated images, an image with the wrong extension, invalid PDFs, encrypted PDFs and PDFs with no pages. Return 422 and clean up files. | Prevents unreadable documents from entering the OCR queue. |
| `test_empty_and_missing_file_rejected` | Empty content or missing multipart `file` returns 422 without persistent changes. | Handles incomplete upload requests. |
| `test_size_limit_accepts_boundary_and_cleans_oversized_upload` | A file one byte over the configured limit returns 413 with no residue; a valid file exactly at the limit succeeds. | Checks size-limit boundaries and cleanup. |
| `test_empty_list_and_missing_receipt` | Empty database produces an empty paginated response; an unknown receipt ID returns 404. | Defines predictable empty/not-found responses. |
| `test_list_pagination_and_status_filter` | Multiple receipt statuses produce correct newest-first pages, filtered totals and empty out-of-range pages. | Checks list navigation and filtering. |
| `test_detail_returns_only_matching_receipt_items_in_line_order` | Populate multiple receipts and out-of-order lines; detail returns only the requested receipt's lines, sorted by line number. | Prevents incorrect receipt/item associations in responses. |
| `test_invalid_pagination_status_and_ids_rejected` | Invalid limits, negative offset, unknown status and invalid IDs return 422. | Checks query and path validation. |
| `test_database_upload_failure_removes_staged_file` | Simulate a database connection failure during upload; return 503 with no row/file and no internal exception details in the response. | Checks cleanup when persistence fails. |
| `test_file_save_failure_rolls_back_receipt` | Simulate failure moving a validated file into place; return 503, roll back the receipt and remove temporary files. | Checks consistency between saved documents and database records. |
| `test_restart_preserves_receipts_and_duplicate_detection` | Start another app against the same temporary storage; existing detail remains readable and the same file still returns 409. | Verifies persistence across application restarts. |
| `test_health_and_queries_report_database_unavailable` | Simulate database failures for health, list and detail; return 503 without exposing internal errors. | Checks consistent dependency-failure responses. |

## Purpose of each OCR test

All OCR API tests use temporary database/upload paths; they never process the
developer's personal receipts. Parser tests use fixed text; engine tests use
generated images and PDFs. Native PDF resources and database connections are
closed explicitly.

| Test | Purpose and expected result |
|---|---|
| `test_extracts_store_day_first_date_currency_total_and_items` | Extract Tesco, a UK date, GBP, exact integer minor-unit amounts and two item lines without warnings. |
| `test_parses_decimal_comma_and_explicit_quantity` | Parse decimal-comma prices and an explicit quantity/unit price consistently. |
| `test_extracts_store_location_from_header_after_name` | Extract a store location from header text following a recognised supermarket name. |
| `test_missing_or_ambiguous_fields_are_not_invented` | Leave unknown store/date/currency and conflicting dates/totals/currencies unresolved with warnings. |
| `test_payment_subtotal_and_tax_lines_are_not_items` | Exclude payment and tax summaries, retain grocery items and parse two-digit years. |
| `test_cashback_and_change_amounts_are_ignored_after_total` | Ignore cash, cashback and change amounts after the printed receipt total. |
| `test_discounts_negative_lines_and_mismatches_require_review` | Preserve positive product lines while flagging discounts/refunds and item/receipt total mismatches. |
| `test_invalid_dates_and_empty_receipt_require_review` | Reject impossible dates and warn when no item lines can be extracted, including a zero total. |
| `test_split_rows_use_quantity_math_when_price_precedes_product` | Verify the generic split-row parser uses quantity × unit price to pair a product with its amount even when OCR reads that amount before the product name, then attaches its discount and reads a following total. |
| `test_lidl_quantity_unit_price_and_discount_persist_with_the_item` | Run Lidl OCR through the API and store one quantity, unit price, gross line total and discount. |
| `test_tesco_item_markers_do_not_replace_the_preceding_product` | Keep `TAPE MEASURE` when an `x` marker and amount follow it, and exclude the marker from the items. |
| `test_tesco_separate_prices_promotions_and_vouchers_are_reconciled` | Verify the generic parser uses reading-order standalone prices, joins wrapped descriptions, attaches promotions and applies a receipt-level voucher to reconcile the printed total. |
| `test_tesco_voucher_discount_persists_at_receipt_level` | Run Tesco OCR through the API and save an unallocated voucher discount on the receipt. |
| `test_rapidocr_joins_lines_and_averages_confidence` | Join RapidOCR lines in recognition order and average its line confidence values. |
| `test_tall_receipt_uses_overlapping_tiles_and_deduplicates_boundary_lines` | Read a tall receipt in full, supplement it with an overlapping footer tile, and remove the repeated row. |
| `test_missing_date_retries_the_footer_before_persisting` | Retry the footer after full-image OCR leaves the date empty, then persist the recovered date. |
| `test_small_images_are_upscaled_and_large_images_keep_their_size` | Inspect images submitted to RapidOCR: 325-pixel-wide images become 3×, 400-pixel-wide images become 2×, larger images retain dimensions, and source images remain unchanged. |
| `test_upscaling_respects_the_pixel_budget` | Skip enlargement when its allocation would exceed the pixel limit; reject an already oversized input. |
| `test_blank_ocr_is_not_reported_as_success` | Reject OCR with no readable text instead of claiming a successful extraction. |
| `test_pdf_text_layer_does_not_require_rapidocr` | Extract embedded PDF text without starting RapidOCR and leave OCR confidence null. |
| `test_pdf_page_limit_is_enforced_before_rendering` | Reject over-limit PDFs before allocating rendered pages. |
| `test_real_rapidocr_reads_synthetic_image` | Use RapidOCR to recognise a generated grocery receipt image and extract its total/items. |
| `test_real_rapidocr_reads_scanned_pdf` | Render a generated image-only PDF and verify RapidOCR recognition. |
| `test_success_persists_raw_text_provisional_fields_and_review_status` | Save text, confidence, timestamps, supermarket/date/total/items and return `needs_review`, excluded from spending totals. |
| `test_review_correction_replaces_items_and_records_audit_values` | Correct a supermarket, total and complete item list; store each before/after change with the editor name. |
| `test_only_review_ready_receipts_can_be_corrected` | Reject a correction before OCR has produced a receipt awaiting review. |
| `test_verification_requires_reconciled_review_and_updates_spending` | Verify a reconciled reviewed receipt, create a status audit record, and include its total in spending results. |
| `test_repeated_or_verified_receipt_ocr_does_not_overwrite` | Reject reprocessing of review-ready or verified receipts and preserve existing results. |
| `test_failures_are_saved_and_retry_creates_new_attempt` | Persist a failed/timed-out attempt, then retry successfully with a new ID without deleting history. |
| `test_missing_or_external_file_fails_without_reading_it` | Reject missing documents and paths outside the configured upload directory before invoking the engine. |
| `test_unknown_receipt_and_no_attempt_return_404` | Return 404 for unknown IDs and latest-result queries before recognition. |
| `test_processing_is_visible_and_second_request_is_rejected` | Expose `processing`/`running` during OCR and prevent a concurrent duplicate request. |
| `test_existing_manual_items_are_preserved` | Refuse OCR when item records already exist, even if receipt status is pending. |
| `test_partial_extraction_saves_warnings_without_guessed_values` | Save partial text/items, leave unrecognised metadata null and require review. |
| `test_persistence_failure_rolls_back_items_and_keeps_raw_result` | Simulate a database write failure; roll back provisional fields/items/store creation but preserve text in the failed attempt. |
| `test_real_ocr_upload_to_provisional_database_records` | Run RapidOCR through the HTTP endpoint and verify saved provisional totals/items and review status. |

## Coverage and limits

These are database integration tests using synthetic records. They cover selected
successful and rejected operations, rather than every field constraint or business
rule. The suite contains 70 tests, including three real-engine checks when
RapidOCR is installed. GitHub Actions is configured in
[database.yml](../.github/workflows/database.yml) to run them on pushes and pull
requests; a successful remote run has not been verified here.

OCR recognition and basic parsing are tested with synthetic documents. Field-level
accuracy on labelled real receipts has not been evaluated. Mobile/desktop workflows,
authentication and Power BI dashboards remain unimplemented. Tests do not imply that
all real supermarket layouts parse correctly.
For storage rules and responsibilities of the future application, see the
[database guide](../docs/database.md). For the implemented HTTP interface and
its current limits, see the [API guide](../docs/api.md).

# Database and API Tests

The 13 tests in [test_database.py](test_database.py) check the implemented SQLite
schema, constraints, and analytical views. They use Python's built-in
`unittest`, with no additional dependencies.

The additional 28 tests in [test_api.py](test_api.py) exercise the FastAPI backend
using TestClient, a temporary SQLite database, a temporary upload directory,
and synthetic PNG/JPEG/PDF documents. [test_ocr.py](test_ocr.py) adds 52 parser,
engine and OCR API tests. [test_analytics.py](test_analytics.py) and
[test_sample_receipt.py](test_sample_receipt.py) add one test each. The full suite
contains **105 tests**. API tests require the dependencies in
`requirements-dev.txt`, including httpx.

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
python -m unittest discover -s tests -p 'test_receipt_images.py' -v
```

Refresh the committed OCR text and parsed metrics for every image in
`receipt-image/` after intentionally changing OCR behaviour:

```bash
python tests/refresh_receipt_image_results.py
```

`test_receipt_images.py` requires every image to have a saved result and checks
that each monetary receipt still reconciles. The points-only Boots slip is kept
as an explicit non-spending fixture.

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

## Purpose of each analytics test

| Test | Scenario and expected result | Why it matters |
|---|---|---|

## Purpose of the public sample-data test

| Test | Scenario and expected result | Why it matters |
|---|---|---|

## Purpose of each API test

Every test creates its own app through `create_app`, starts its lifespan using
TestClient, and cleans up the client before removing temporary files. All requests
are in-process; no running server or real grocery documents are required.

| Test | Scenario and expected result | Why it matters |
|---|---|---|

## Purpose of each OCR test

All OCR API tests use temporary database/upload paths; they never process the
developer's personal receipts. Parser tests use fixed text; engine tests use
generated images and PDFs. Native PDF resources and database connections are
closed explicitly.

| Test | Purpose and expected result |
|---|---|
| `test_extracts_store_day_first_date_currency_total_and_items` | Extract Tesco, a UK date, GBP, exact integer minor-unit amounts and two item lines without warnings. |
| `test_extracts_store_location_from_header_after_name` | Extract a store location from header text following a recognised supermarket name. |
| `test_any_total_label_is_used_as_the_receipt_total` | Treat a line beginning with `Total`, such as `Total payable`, as the receipt total. |
| `test_missing_or_ambiguous_fields_are_not_invented` | Leave unknown store/date/currency and conflicting dates/totals/currencies unresolved with warnings. |
| `test_payment_subtotal_and_tax_lines_are_not_items` | Exclude payment and tax summaries, retain grocery items and parse two-digit years. |
| `test_cashback_and_change_amounts_are_ignored_after_total` | Ignore cash, cashback and change amounts after the printed receipt total. |
| `test_invalid_dates_and_empty_receipt_require_review` | Reject impossible dates and warn when no item lines can be extracted, including a zero total. |
| `test_text_month_dates_support_common_receipt_formats` | Parse abbreviated/full English month names in day-first and month-first forms, including ordinal days, compact `31OCT2026`, OCR `310CT2026`, and two-digit years, while rejecting impossible dates. |
| `test_short_ocr_prefix_before_balance_due_is_ignored` | Read a printed item count before `Balance Due` without losing the following receipt total. |
| `test_total_label_can_appear_later_in_a_summary_line` | Recognise `Total`, `Amount Due`, or `Balance Due` when the settlement label appears later in a summary line. |
| `test_unmarked_decimals_are_not_amounts` | Keep bare decimals out of amounts when neither a merchant nor a currency context is recognised. |
| `test_negative_amount_is_the_previous_items_discount` | Treat a negative amount as the preceding item’s discount. |
| `test_vat_number_and_url_end_the_receipt_header` | Start item parsing after VAT-number and website header rows. |
| `test_consecutive_text_lines_are_joined_before_the_amount` | Join a recognised wrapped product-name continuation before its amount. |
| `test_integer_quantity_and_two_ocr_amounts_are_math_checked` | Read an integer as quantity, retain both OCR amounts, and report a mismatched multiplication without replacing either value. |
| `test_quantity_and_unit_price_positions_are_not_fixed` | Resolve quantity and unit price on either side of Original using the exact OCR values and their multiplication relationship. |
| `test_quantity_price_token_accepts_optional_multiplication_marker` | Parse quantity and unit price joined by `x`, `×`, `@`, or whitespace without creating a false item name. |
| `test_first_price_uses_the_previous_line_instead_of_a_numbered_header` | Start the item section at the valid text immediately before the first price so a numbered address is not treated as a product. |
| `test_math_mismatch_preserves_ocr_amount` | Preserve an OCR amount when it does not equal quantity × unit price; arithmetic must not replace the source value. |
| `test_promotion_markers_group_items_and_keep_each_discount` | Treat common `for`/`Fr` and `CC` rows as promotion signs, keep the advertised price out of Original, and retain every following printed discount. |
| `test_multi_buy_group_spans_its_advertised_item_quantity` | Link the current and following items to one promotion group until the advertised multi-buy quantity is reached. |
| `test_rapidocr_joins_lines_and_averages_confidence` | Join RapidOCR lines in recognition order and average its line confidence values. |
| `test_tall_receipt_uses_overlapping_tiles_and_deduplicates_boundary_lines` | Read a tall receipt in full, supplement it with an overlapping footer tile, and remove the repeated row. |
| `test_receipt_region_is_located_before_ocr` | Detect a receipt quadrilateral against a photograph background and rectify that region before OCR. |
| `test_missing_date_retries_the_footer_before_persisting` | Retry the footer after full-image OCR leaves the date empty, then persist the recovered date. |
| `test_small_images_are_upscaled_and_large_images_keep_their_size` | Inspect images submitted to RapidOCR: 325-pixel-wide images become 3×, 400-pixel-wide images become 2×, larger images retain dimensions, and source images remain unchanged. |
| `test_upscaling_respects_the_pixel_budget` | Skip enlargement when its allocation would exceed the pixel limit; reject an already oversized input. |
| `test_blank_ocr_is_not_reported_as_success` | Reject OCR with no readable text instead of claiming a successful extraction. |
| `test_pdf_text_layer_does_not_require_rapidocr` | Extract embedded PDF text without starting RapidOCR and leave OCR confidence null. |
| `test_pdf_page_limit_is_enforced_before_rendering` | Reject over-limit PDFs before allocating rendered pages. |
| `test_real_rapidocr_reads_synthetic_image` | Use RapidOCR to recognise a generated grocery receipt image and extract its total/items. |
| `test_real_rapidocr_reads_scanned_pdf` | Render a generated image-only PDF and verify RapidOCR recognition. |
| `test_success_persists_raw_text_provisional_fields_and_review_status` | Save text, confidence, timestamps and receipt metadata; keep provisional items in OCR output until verification. |
| `test_review_correction_replaces_items_and_records_audit_values` | Correct a supermarket, total and complete item list; store each before/after change with the editor name. |
| `test_only_review_ready_receipts_can_be_corrected` | Reject a correction before OCR has produced a receipt awaiting review. |
| `test_verification_requires_reconciled_review_and_updates_spending` | Verify a reconciled reviewed receipt, create a status audit record, and include its total in spending results. |
| `test_verification_persists_discount_reasons_and_promotion_group` | Persist separate discount amounts, their reasons, and their shared promotion group when a reviewed receipt is verified. |
| `test_manual_b_and_m_supermarket_is_created_when_the_receipt_is_verified` | Confirm a manually reviewed B&M store name is created in the selected database's `Supermarket` table during verification. |
| `test_verification_matches_a_leading_brand_to_the_product` | Match a leading known brand and save its `brand_id` on the product created during verification. |
| `test_existing_item_name_does_not_imply_its_brand_on_a_new_receipt` | Use an existing brand-stripped item name to recognise the product, while keeping its historical brand out of a new ambiguous receipt line. |
| `test_unknown_brand_candidate_is_not_saved_as_an_alias` | Suggest an unknown leading brand, accept a different final brand during verification, and retain the original item name without adding an alias. |
| `test_final_brand_does_not_strip_a_candidate_from_the_product_name` | Keep a candidate such as `Croissant` in the product name when the final verified brand is Lidl. |
| `test_unbranded_item_uses_editable_supermarket_default` | Use the receipt supermarket as the editable brand default and accept it when the reviewer verifies the receipt. |
| `test_category_suggestion_can_be_overridden_before_verification` | Suggest a category from an explicit product term, save a reviewer-selected replacement, and write it to the verified receipt item. |
| `test_strawberry_flavour_is_not_suggested_as_fruit` | Categorise a flavour-labelled biscuit as a snack instead of treating its flavour word as produce. |
| `test_repeated_or_verified_receipt_ocr_does_not_overwrite` | Reject reprocessing of review-ready or verified receipts and preserve existing results. |
| `test_failures_are_saved_and_retry_creates_new_attempt` | Persist a failed/timed-out attempt, then retry successfully with a new ID without deleting history. |
| `test_missing_or_external_file_fails_without_reading_it` | Reject missing documents and paths outside the configured upload directory before invoking the engine. |
| `test_unknown_receipt_and_no_attempt_return_404` | Return 404 for unknown IDs and latest-result queries before recognition. |
| `test_processing_is_visible_and_second_request_is_rejected` | Expose `processing`/`running` during OCR and prevent a concurrent duplicate request. |
| `test_existing_manual_items_are_preserved` | Refuse OCR when item records already exist, even if receipt status is pending. |
| `test_partial_extraction_saves_warnings_without_guessed_values` | Save partial text/items, leave unrecognised metadata null and require review. |
| `test_ocr_keeps_items_out_of_database_until_verification` | Confirm OCR does not insert `ReceiptItem` rows before verification. |
| `test_real_ocr_upload_to_provisional_database_records` | Run RapidOCR through the HTTP endpoint and verify saved provisional totals/items and review status. |

## Coverage and limits

These are database integration tests using synthetic records. They cover selected
successful and rejected operations, rather than every field constraint or business
rule. The suite contains 105 tests, including three real-engine checks when
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

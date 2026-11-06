# Spending backend

This package contains the FastAPI application, local OCR workflow, provisional
receipt parser, review/verification logic, SQLite access, and upload validation.

## Files

| File | Responsibility |
|---|---|
| [`api.py`](api.py) | FastAPI routes, request/response models, uploads, OCR execution, review, verification, deletion, and reports |
| [`database.py`](database.py) | SQLite connection and repeatable schema/seed initialisation |
| [`ocr_engine.py`](ocr_engine.py) | Receipt-region detection, colour/contrast preparation, RapidOCR, PDF extraction, and footer retry |
| [`ocr_service.py`](ocr_service.py) | Runs OCR, parses its text, and persists each OCR attempt |
| [`receipt_parser.py`](receipt_parser.py) | Generic receipt metadata, amount, item, quantity, unit-price, discount, and validation parsing |
| [`review.py`](review.py) | Provisional item presentation, brand/category suggestions, corrections, and verification writes |
| [`uploads.py`](uploads.py) | File type, extension, image, PDF, size, and document validation |

## Post-OCR parsing rules

The parser uses the same item rules for every merchant. Merchant names are used
as receipt metadata and as permission to read bare decimal amounts; they do not
select a merchant-specific item layout.

| Rule | Behaviour | Code |
|---|---|---|
| Marked amounts | `£1.20`, `€1.20`, and `$1.20` are amounts with exactly two decimal places. | [`receipt_parser.py` lines 8–9](receipt_parser.py#L8-L9) |
| ISO currency amounts | `GBP 1.20`, `EUR 1.20`, and `USD 1.20` are normalised to their currency symbols before parsing. | [`receipt_parser.py` lines 103–111](receipt_parser.py#L103-L111) |
| Bare decimal amounts | Values such as `1.20 A` and `2.19 C` are accepted only when the receipt identifies a merchant or currency. Without either context, bare numbers are not money. | [`receipt_parser.py` lines 114–131](receipt_parser.py#L114-L131) |
| Visual row order | RapidOCR boxes are deskewed, grouped by their vertical centres, and sorted left-to-right so a right-column price stays with its left-column product name. | [`ocr_engine.py`](ocr_engine.py) |
| Item-section start | If VAT-number or website rows occur before the total, item parsing starts after the last such row. | [`receipt_parser.py` lines 168–175](receipt_parser.py#L168-L175) |
| Item name | A textual candidate must appear before its Original amount. Summary and amount-only rows cannot be names. | [`receipt_parser.py` lines 149–155](receipt_parser.py#L149-L155), [`lines 224–251`](receipt_parser.py#L224-L251) |
| Wrapped name | Recognised wrapped rows, including lines beginning with `&`, `and`, `flavour`, or a pack size, are joined to the preceding name. | [`receipt_parser.py` lines 158–163](receipt_parser.py#L158-L163), [`lines 230–235`](receipt_parser.py#L230-L235) |
| Discount | A negative two-decimal amount appears after Original and attaches to the preceding item. It never creates an item or an amount through arithmetic. | [`receipt_parser.py` lines 17 and 201–206](receipt_parser.py#L17), [`receipt_parser.py` lines 201–206](receipt_parser.py#L201-L206) |
| Promotion marker | `3 for £2.00`, `3 for 2.00`, `MnM 3 for £2.00`, `2 Fr £7.50`, `3 for 2`, `CC £1.00`, and `CC 1` are promotion signs. A sign does not create or end an item, and its advertised price is not Original. | [`receipt_parser.py` lines 21–27](receipt_parser.py#L21-L27), [`lines 197–208`](receipt_parser.py#L197-L208) |
| Promotion group | A multi-buy sign groups the current item and following items until its printed quantity is filled. The following negative amounts stay with their current item and reference that group. | [`receipt_parser.py` lines 232–246](receipt_parser.py#L232-L246), [`lines 264–302`](receipt_parser.py#L264-L302) |
| Multiple discounts | Every printed negative amount is retained separately with its OCR text, reason, and optional promotion group. `ReceiptItem.discount_pence` is the sum used for reconciliation. | [`receipt_parser.py` lines 56–80](receipt_parser.py#L56-L80), [`lines 293–301`](receipt_parser.py#L293-L301) |
| Quantity and unit-price token | `2 x 2.29`, `2 × £2.29`, `2 @ 2.29`, and `2 2.29` mean quantity `2` and unit price `£2.29`. | [`receipt_parser.py` lines 18–20](receipt_parser.py#L18-L20), [`lines 207–217`](receipt_parser.py#L207-L217) |
| Standalone quantity | An integer near the open item is quantity. Quantity may appear before or after Original. | [`receipt_parser.py` lines 218–223](receipt_parser.py#L218-L223) |
| Quantity-column layout | A leading integer is removed as quantity only when several rows establish the same `quantity + product + right-side amount` layout. Multiplication tokens such as `2 × 1.64` cannot activate this mode. | [`receipt_parser.py`](receipt_parser.py) |
| Unassigned OCR amount | A printed amount displaced by skew or a fold is queued and matched to the next product token in OCR order. Only detected values are used; no price is calculated. | [`receipt_parser.py`](receipt_parser.py) |
| Flexible numeric order | Only `Name → Original` and `Original → Discount` are fixed. Quantity and unit price have no fixed position. | [`receipt_parser.py` lines 199–252](receipt_parser.py#L199-L252) |
| Mathematical validation | The parser tests `quantity × unit price = original`. If the reversed OCR amount roles satisfy the equation, it assigns those existing OCR values accordingly. If neither relationship works, it adds a warning. It never calculates a replacement amount. | [`receipt_parser.py` lines 183–197](receipt_parser.py#L183-L197) |
| Receipt total | `Total`, `Grand Total`, `Amount Due`, and `Balance Due` identify the receipt total. A total amount may be on the same or following row. | [`receipt_parser.py` lines 10–15](receipt_parser.py#L10-L15), [`lines 304–347`](receipt_parser.py#L304-L347) |
| Date candidates | Every valid printed date is returned in `date_candidates`. One unique date is selected automatically; multiple dates remain available in the review dropdown and manual date input. | [`receipt_parser.py`](receipt_parser.py) |
| Reconciliation | The sum of Original minus item discounts and receipt discount is compared with the printed total. A mismatch produces a review warning and does not alter data. | [`receipt_parser.py` lines 348–357](receipt_parser.py#L348-L357) |

RapidOCR receives the already oriented receipt with per-text-box direction
classification disabled. This prevents short amounts such as `-0.39` from being
independently rotated by 180°. See
[`ocr_engine.py`](ocr_engine.py#L217).

## Frontend validation

The desktop table independently compares `quantity × unit price` with Original.
A mismatch applies the `requires-review` class and displays the row in red. The
frontend check is in [`desktop/src/App.tsx`](../desktop/src/App.tsx#L470), with
its styling in [`desktop/src/styles.css`](../desktop/src/styles.css#L84).

## Data rule

`original_pence`, `unit_price_pence`, and each `ItemDiscount.amount_pence` must
come from OCR or human review. `ReceiptItem.discount_pence` is only the stored
sum of those printed discounts. Mathematics may select relationships and report
errors, but it must not invent or overwrite a monetary value.


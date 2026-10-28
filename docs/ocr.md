# Grocery Receipt OCR

The backend recognises uploaded JPG, PNG and scanned PDF receipts locally with
RapidOCR. No receipt image is sent to an external recognition service. PDF files
with embedded text use pypdf directly; scanned PDF pages are rendered with
pypdfium2 and passed to RapidOCR.

## Setup

Install the application dependencies and run the API from the repository root:

```bash
python -m pip install -r requirements-dev.txt
python -m uvicorn spending.api:app --reload --host 127.0.0.1 --port 8000
```

RapidOCR downloads its local model files the first time it processes an image.
This can make the first request slower. Subsequent recognitions reuse the local
model cache. No separate native Tesseract installation is required.

## Compare local OCR engines

The isolated [OCR benchmark folder](../ocr-benchmark/README.md) contains three
sample receipts, pinned comparison dependencies, a runnable benchmark, and
machine-readable results for Tesseract, RapidOCR and PaddleOCR. RapidOCR is the
application engine; the other engines remain benchmark-only comparisons.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `GROCERY_OCR_MAX_PAGES` | `10` | Maximum accepted PDF pages for recognition |

The parser currently targets English grocery receipts and UK/day-first dates.
Changing an OCR model does not add another receipt-layout parser.

## Use through Swagger

1. Open <http://127.0.0.1:8000/docs>.
2. Use `POST /receipts` to upload a receipt; copy the returned `id`.
3. Use `POST /receipts/{receipt_id}/ocr` with that ID to recognise it.
4. Use `GET /receipts/{receipt_id}/ocr` to retrieve the latest attempt and text.
5. Use `GET /receipts/{receipt_id}` to inspect provisional fields and item lines.

The OCR POST is synchronous: it returns after processing, not a background job.
The first image request may include RapidOCR model initialisation. Upload itself
returns quickly with `pending`; it does not automatically launch OCR.

```bash
curl -X POST http://127.0.0.1:8000/receipts/1/ocr
curl http://127.0.0.1:8000/receipts/1/ocr
curl http://127.0.0.1:8000/receipts/1
```

## Results and database writes

The response includes attempt ID, receipt ID, engine/version, status, confidence,
timestamps, and any error message. Successful attempts include `output`:

- `text`: full extracted text, with pages separated by blank lines.
- `pages`: page number, text, source (`rapidocr` or `pdf_text`), and confidence.
- `confidence`: mean of the available RapidOCR line confidence scores, or null
  for a PDF containing only embedded text. This is not field-level accuracy.
- `engine_version`: installed RapidOCR package version when RapidOCR was used.
- `parsed`: provisional supermarket name, date, currency, total, item lines and
  warnings about missing/ambiguous fields or reconciliation problems.

The same JSON is stored in the existing `ocr_runs.raw_output` TEXT field. The
existing `Supermarket`, `Item`, `Receipt`, and `ReceiptItem` table names remain
unchanged.

Receipt state transitions are:

```text
pending / failed -> processing -> needs_review  (text extraction succeeded)
                              -> failed        (recognition or persistence failed)
```

An OCR attempt transitions `running -> succeeded/failed`, with completion time.
Failure messages and any result available before a database write failure are
preserved. A retry of a failed receipt creates a separate attempt; older attempts
remain in `ocr_runs`. The GET endpoint returns only the newest one.

On success, provisional date, total, currency and supermarket reference are saved
to `Receipt`, and parsed item lines to `ReceiptItem`. Supported supermarket names
use a location-unspecified `Supermarket` record; an existing matching name with
empty location is reused. Product/category matches are left null. Unknown fields
remain null, except currency, which retains the existing GBP schema default when
no explicit currency was identified; a warning identifies this for review.

Only `pending`/`failed` receipts without existing items or correction records can
start OCR. Processing, review-ready and verified receipts return 409. OCR never
automatically verifies a receipt or adds it to spending totals. Use the review
endpoints in the API guide to correct and verify a `needs_review` receipt.

## Parsing and limits

- Before RapidOCR runs, images are EXIF-oriented, converted to grayscale and
  contrast-adjusted. When image width is below 800 pixels, LANCZOS enlargement
  uses the smallest integer scale that reaches 800 pixels, capped at 3× and by
  the 20-million-pixel budget. Original files are unchanged.
- Supported metadata includes selected supermarket header names, ISO dates,
  day-first dates, explicit GBP/EUR/USD markers, and labelled totals.
- Day-first two-digit years are interpreted as 2000–2099. Multiple distinct dates,
  totals or currencies are left unresolved rather than choosing one silently.
- Product lines use trailing two-decimal amounts (decimal point or comma).
  Explicit `2 x Milk` and `Milk 2 x 1.20 2.40` quantity forms are supported.
  Other quantities default to one and require manual checking.
- Payment/subtotal/tax lines are excluded from product lines. Discounts, refunds,
  negative lines and item/receipt mismatches produce review warnings; automatic
  allocation of these adjustments is not implemented.
- Text fields and rows are suggestions from a simple parser. Store-specific
  layouts, weighted goods, rotated/blurred photographs, multi-line descriptions,
  complex promotions and other languages need further work and real receipt
  evaluation. Passing synthetic tests is not a measured real-world accuracy rate.
- Images/rendered PDF pages are limited to 20 million pixels; total extracted
  text is capped at 100,000 characters. PDF rendering uses a shared lock because
  PDFium is not thread-safe. Native resources are closed explicitly.
- A process crash can leave an attempt `running` and its receipt `processing`.
  Automatic recovery, worker queues and cancellation are not implemented yet.

| HTTP status | Meaning |
|---|---|
| 200 | Recognition succeeded, or latest attempt retrieved |
| 404 | Unknown receipt or no OCR attempt yet (GET) |
| 409 | Receipt already being processed/reviewed/verified, or has protected items/corrections |
| 422 | No readable text, missing stored document, unsupported document characteristics or limits exceeded |
| 503 | RapidOCR is unavailable, could not initialise, or OCR results could not be saved |
| 500 | Unexpected recognition failure, saved as a failed attempt without returning internal details |

Next steps are richer receipt parsers, field-level OCR evaluation against labelled
real receipts, reporting APIs, and asynchronous work
if local synchronous processing becomes too slow. See [API setup](api.md),
[database structure](../data/README.md), and [test descriptions](../tests/README.md).

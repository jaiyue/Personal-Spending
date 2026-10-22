# Grocery Receipt OCR

The backend now supports local OCR for the uploaded JPG/PNG/PDF receipts. No
receipt is sent to an external recognition service. Tesseract recognises images;
PDF pages with embedded text use pypdf, while scanned pages are rendered with
pypdfium2 and recognised by Tesseract.

## Setup

The development computer already has Tesseract 5.5.0 and English language data.
For another computer, install the native engine separately from Python packages:

```bash
# macOS with Homebrew
brew install tesseract

# Ubuntu/Debian
sudo apt-get update
sudo apt-get install tesseract-ocr tesseract-ocr-eng
```

For Windows, install Tesseract and either add it to PATH or set
`GROCERY_TESSERACT_CMD` to its executable path. Then install the Python dependencies
and start the API from the repository root:

```bash
python -m pip install -r requirements-dev.txt
python -m uvicorn spending.api:app --reload --host 127.0.0.1 --port 8000
```

## Compare local OCR engines

The isolated [OCR benchmark folder](../ocr-benchmark/README.md) contains three
sample receipts, pinned comparison dependencies, a runnable benchmark, and
instructions for generating machine-readable results for Tesseract, RapidOCR
and PaddleOCR. The benchmark reports raw text, engine versions, confidence
values and timings; it does not score or rank the engines.

Configuration is read when `create_app()` constructs its local OCR engine:

| Variable | Default | Purpose |
|---|---|---|
| `GROCERY_TESSERACT_CMD` | `tesseract` | Executable name or path (passed directly, without a shell) |
| `GROCERY_OCR_LANGUAGE` | `eng` | Installed Tesseract language code(s); e.g. `eng+chi_sim` requires both datasets |
| `GROCERY_OCR_TIMEOUT_SECONDS` | `60` | Positive timeout for each image/page recognition subprocess |
| `GROCERY_OCR_MAX_PAGES` | `10` | Maximum accepted PDF pages for recognition |

The parser currently targets English grocery receipts and UK/day-first dates.
Selecting another OCR language does not add another receipt-layout parser.

## Use through Swagger

1. Open <http://127.0.0.1:8000/docs>.
2. Use `POST /receipts` to upload a receipt; copy the returned `id`.
3. Use `POST /receipts/{receipt_id}/ocr` with that ID to recognise it.
4. Use `GET /receipts/{receipt_id}/ocr` to retrieve the latest attempt and text.
5. Use `GET /receipts/{receipt_id}` to inspect provisional fields and item lines.

The OCR POST is synchronous: it returns after processing, not a background job.
A second request can read `processing`/`running` during recognition. Upload itself
still returns quickly with `pending`; it does not automatically launch OCR.

```bash
curl -X POST http://127.0.0.1:8000/receipts/1/ocr
curl http://127.0.0.1:8000/receipts/1/ocr
curl http://127.0.0.1:8000/receipts/1
```

## Results and database writes

The response includes attempt ID, receipt ID, engine/version, status, confidence,
timestamps, and any error message. Successful attempts include `output`:

- `text`: full extracted text, with pages separated by blank lines.
- `pages`: page number, text, source (`tesseract` or `pdf_text`), and confidence.
- `confidence`: mean of the available per-page OCR confidence scores, or null
  for a PDF containing only embedded text. This is not field-level accuracy.
- `engine_version`: Tesseract version when Tesseract was used.
- `parsed`: provisional supermarket name, date, currency, total, item lines and
  warnings about missing/ambiguous fields or reconciliation problems.

The same JSON is stored in the existing `ocr_runs.raw_output` TEXT field. No schema
migration or change to the existing `Supermarket`, `Item`, `Receipt`, and
`ReceiptItem` table names is required.

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
automatically verifies a receipt or adds it to spending totals. Existing reviewed
records are not replaced by rerunning recognition.

## Parsing and limits

- Before OCR, images are EXIF-oriented, converted to grayscale and contrast-adjusted.
  When image width is below 800 pixels, LANCZOS enlargement uses the smallest
  integer scale that reaches 800 pixels, capped at 3× and further limited by the
  20-million-pixel budget. If 2× would exceed the budget, no enlargement is applied.
  Widths of 800 pixels or more keep their dimensions. Original files are unchanged.
  The same preprocessing applies to rendered scanned-PDF pages.
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

### Low-resolution Tesco example

The supplied `template-tesco-1-screenshot-1.png` is 325 × 872 pixels. Before
enlargement, local Tesseract read `TOTAL £99.30` and `CASH 260.00`. After 3×
enlargement to 975 × 2616, the current engine reads `TOTAL £55.30`, `CASH £60.00`
and `CHANGE DUE £4.70`, matching the source image.

The image itself contains 17 item lines totalling £89.60, not £55.30. The £34.30
difference still produces a review warning. Repeated lines are visible in the
original and are not removed automatically. This is a verified local example,
not a measured OCR accuracy rate. New recognition requests use the preprocessing;
existing stored OCR results are preserved, and the review/verified rerun protection
still applies. The source screenshot is not required by automated tests, which
generate their own documents.

| HTTP status | Meaning |
|---|---|
| 200 | Recognition succeeded, or latest attempt retrieved |
| 404 | Unknown receipt or no OCR attempt yet (GET) |
| 409 | Receipt already being processed/reviewed/verified, or has protected items/corrections |
| 422 | No readable text, missing stored document, unsupported document characteristics or limits exceeded |
| 503 | Tesseract/configured language is unavailable, or OCR results could not be saved |
| 504 | Tesseract recognition timed out |
| 500 | Unexpected recognition failure, saved as a failed attempt without returning internal details |

Next steps are manual correction/confirmation APIs, richer receipt parsers,
field-level OCR evaluation against labelled real receipts, and asynchronous work
if local synchronous processing becomes too slow. See [API setup](api.md),
[database structure](../data/README.md), and [test descriptions](../tests/README.md).

References: [Tesseract command-line usage](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html),
[pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html),
and [pypdfium2 threading/resource rules](https://pypdfium2.readthedocs.io/en/stable/python_api.html).

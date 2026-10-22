# Grocery Receipt API

The FastAPI backend uploads grocery receipt documents and queries records in the
existing `Receipt` and `ReceiptItem` tables. It preserves the original database
table names and uses the existing migration/backup tools at application startup.
Local OCR and provisional grocery parsing are implemented. Uploaded receipts
start as `pending`; an explicit OCR request saves results as `needs_review`.
Manual correction and verification remain the next stages. See the
[OCR guide](ocr.md) for native Tesseract setup, parsing limits and configuration.

## Install and run

Use Python 3.13 (the locally tested and CI version) from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m uvicorn spending.api:app --reload --host 127.0.0.1 --port 8000
```

For running the API without tests, install `requirements.txt` instead. On Windows,
activate the environment with `.venv\Scripts\Activate.ps1` in PowerShell.

- Interactive API documentation: <http://127.0.0.1:8000/docs>
- OpenAPI schema: <http://127.0.0.1:8000/openapi.json>
- Health check: <http://127.0.0.1:8000/health>

The current API is a local development service without authentication. The run
command binds to the local computer. Access control is still a roadmap item.

## Configuration

| Environment variable | Default | Meaning |
|---|---|---|
| `GROCERY_DATABASE_PATH` | `<repository>/data/spending.db` | SQLite database file |
| `GROCERY_UPLOAD_DIR` | `<repository>/data/uploads` | Directory for receipt documents |
| `GROCERY_MAX_UPLOAD_BYTES` | `10485760` (10 MiB) | Positive maximum size of one uploaded file |

Default paths are based on the repository location, not the shell's working
directory. Explicit relative paths are resolved against the working directory.
Set these variables before launching Uvicorn. `create_app(database_path,
upload_dir, max_upload_bytes)` also accepts overrides for tests or other local
instances. Importing the module does not initialise or modify a database;
initialisation happens when the app's lifespan starts.

## Endpoints

| Method | Path | Behaviour |
|---|---|---|
| GET | `/health` | Check that the receipt table can be queried; return `status` and `database` as `ok` |
| POST | `/receipts` | Upload one multipart `file`; create a pending receipt and return metadata with HTTP 201 |
| GET | `/receipts` | Return a paginated receipt list, most recent ID first |
| GET | `/receipts/{receipt_id}` | Return receipt metadata and `items`, ordered by line number |
| POST | `/receipts/{receipt_id}/ocr` | Recognise a pending/failed receipt synchronously and save provisional results |
| GET | `/receipts/{receipt_id}/ocr` | Retrieve the latest attempt, raw text, confidence, parsed fields/items or failure details |

List query parameters:

- `limit`: 1–100, default 20.
- `offset`: zero or greater, default 0.
- `status`: optional `pending`, `processing`, `needs_review`, `verified`, or `failed`.

The list response contains `items`, `total` (after filtering), `limit`, and
`offset`. A receipt ID must be a positive integer. Detail queries return only
the matching receipt's lines, and an unprocessed upload has an empty `items` list.

## Upload example

```bash
curl -F 'file=@/path/to/grocery-receipt.png' http://127.0.0.1:8000/receipts
curl 'http://127.0.0.1:8000/receipts?status=pending&limit=20&offset=0'
curl http://127.0.0.1:8000/receipts/1
curl -X POST http://127.0.0.1:8000/receipts/1/ocr
curl http://127.0.0.1:8000/receipts/1/ocr
```

A successful upload returns a `Location: /receipts/{id}` header and receipt fields
including `id`, `status`, `source_type`, `source_path`, `file_sha256`, and
`created_at`. The source is `upload`. `supermarket_id`, `purchase_date`, and
`total_minor` are null until processing/review supplies them. Currency initially
uses the schema's GBP default; it is not inferred from the document.

`source_path` for API-created records is a generated basename under the configured
upload directory. It does not contain the client-supplied filename or an absolute
server path. Example: `47d1d3b394c14f17b8f7d49d51428492.png`. Files are not exposed
as a static directory. Keep both the database and uploads when backing up receipts;
the migration backup mechanism only backs up SQLite, not the uploaded documents.

## File handling and errors

- Supported extensions: `.jpg`, `.jpeg`, `.png`, `.pdf`, case-insensitive.
- MIME metadata must match the extension; missing or generic
  `application/octet-stream` metadata is allowed, with content validation.
- Pillow verifies and decodes images. The image format must match the extension.
  pypdf checks PDF structure; encrypted or zero-page PDFs are rejected. Parsing
  validates document readability, not whether its contents are a grocery receipt.
- File bytes are read in chunks, capped at the configured per-file limit, and
  hashed with SHA-256. The size check runs after multipart parsing; this is not
  a whole-request ingress limit.
- A UUID filename avoids reusing client paths. Temporary files are removed on
  rejected uploads, and handled save failures roll back the receipt and clean up
  its file. Filesystem and SQLite changes are not a distributed transaction;
  an abrupt process termination can leave an orphaned file for later cleanup.
- The database's unique hash constraint handles duplicate uploads, including
  concurrent attempts. Different images of the same paper receipt have different
  hashes and require later business-level duplicate detection.

| Status | Meaning |
|---|---|
| 201 | File saved and pending receipt created |
| 404 | Receipt ID does not exist |
| 409 | Identical file already uploaded; `detail.receipt_id` identifies the existing receipt |
| 413 | File exceeds the configured size limit |
| 415 | Unsupported extension or mismatched MIME metadata |
| 422 | Missing/empty/unreadable file, mismatched image content, encrypted/empty PDF, or invalid query/path input |
| 503 | Storage or database operation failed; internal error details are not returned |

No schema migration was needed for these endpoints. Uploads and OCR populate
existing tables, including `ocr_runs`. Successful OCR is always marked for review;
correction audit writes, verification and aggregate reporting APIs remain pending.
See the [OCR guide](ocr.md), [database guide](database.md),
[data structure](../data/README.md), and [test guide](../tests/README.md).

Implementation follows FastAPI's official guides for
[file uploads](https://fastapi.tiangolo.com/tutorial/request-files/),
[lifespan setup](https://fastapi.tiangolo.com/advanced/events/), and
[TestClient testing](https://fastapi.tiangolo.com/tutorial/testing/).

# Personal Spending — Grocery & Supermarket Price Intelligence

A grocery spending management and supermarket price comparison module that combines data engineering, analytics, and mobile and desktop interfaces.

**Current scope: grocery only.** All receipts, items, shopping lists, budgets,
and spending reports in this module relate to grocery purchases. Other personal
expense types, such as rent, transport, utilities, and entertainment, are outside
the current scope. Grocery is implicit in the module; there is no separate
expense-type selector or general-purpose expense-type table.

Product categories describe grocery groups, such as produce, dairy, and grains.
They are not separate personal expense types. An overall budget or spending
total means the total for grocery purchases in this module.

The project consists of three integrated components:

- **Data Analytics Pipeline:** Processes receipt data, tracks product prices, and supports analytical reporting using Python, SQL, and Power BI.
- **Mobile App:** Provides a user-friendly interface for receipt scanning, expense tracking, product price comparison, and shopping management.
- **Desktop Web Interface:** Focuses on uploading existing receipt images or PDF files and viewing spending and price analytics in a desktop browser. Receipt photography and camera access are not required.

**Status:** In Development

The database foundation is complete: 12 business tables, one migration metadata
table, six analytical views, repeatable initialisation with backups, and 12 passing
local database tests. The FastAPI backend now supports health checks, receipt
uploads, paginated lists, receipt details and local RapidOCR/PDF OCR. It saves
raw text, confidence and provisional grocery fields/items for manual review.
The suite has **61 passing tests** (12 database, 21 upload/query API, 28 OCR/parser).
Manual correction and verification endpoints are implemented. The desktop page
supports upload, OCR review and verification; mobile interfaces, reporting APIs,
Pandas workflows, and Power BI dashboards remain planned.

### Run the backend

Use Python 3.13 from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m uvicorn spending.api:app --reload --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/docs> to try the API. `POST /receipts` accepts JPG,
PNG, and PDF grocery receipts up to 10 MiB; uploads are stored locally and
recorded as `pending`. After uploading, use `POST /receipts/{receipt_id}/ocr` in
the same documentation page to recognise it, then `GET /receipts/{receipt_id}/ocr`
to view the text and suggestions. Results become `needs_review` and are not
automatically included in spending totals. Use `PATCH /receipts/{receipt_id}/review`
to correct fields/items and `POST /receipts/{receipt_id}/verify` after item totals
reconcile. RapidOCR recognises images and scanned PDF pages locally; its model
files download on first image recognition.
See the [API guide](docs/api.md) and [OCR guide](docs/ocr.md) for setup and limits.

### Run the desktop page

Start the backend first, then run the React/Vite desktop page in a second terminal:

```bash
cd desktop
npm install
npm run dev
```

Open <http://127.0.0.1:5173>. The page uploads a JPG, PNG or PDF receipt, starts
OCR immediately, and shows stored text, extracted fields, item lines, review
controls and deletion. Set `VITE_API_BASE` when the API is not at
`http://127.0.0.1:8000`.

### RapidOCR image preprocessing

Before RapidOCR runs, images are EXIF-oriented, converted to grayscale and
contrast-adjusted. Images narrower than 800 pixels are enlarged using LANCZOS,
up to 3×, while preserving aspect ratio and staying within the 20-million-pixel
limit. Larger images retain their dimensions. The original uploaded file is
unchanged; preprocessing applies only to the in-memory OCR input.

For the observed recognition errors, their causes, fixes and verification results,
see [Issues and Resolutions](#9-issues-and-resolutions). Existing saved OCR attempts
are not automatically rewritten.

## 1. Key Features

- **Receipt Processing:** OCR-based receipt extraction, manual correction, duplicate detection, and data validation.
- **Grocery Expense Tracking:** Monitor grocery spending by month, grocery product category, and supermarket, with optional grocery budget tracking.
- **Price Intelligence:** Track historical product prices, calculate unit prices, and compare equivalent products across supermarkets.
- **Shopping Management:** Create grocery shopping lists and estimate grocery basket costs.
- **Product Quality Log:** Record product issues and purchase-related notes.
- **Data Analytics:** Build Power BI dashboards for grocery spending trends, supermarket price analysis, and data quality monitoring.

### Desktop Workflow

1. Upload existing receipt images or PDF files from the computer.
2. Review OCR results and correct receipt details before saving verified records.
3. View grocery spending summaries and trends, with filters for date, grocery product category, and supermarket.
4. Explore product price history and supermarket comparisons.

The mobile app supports taking receipt photos. The desktop interface focuses on file uploads and analytical views, with no receipt photography workflow.

## 2. System Architecture

The following diagram shows the target architecture. The SQLite database,
initialisation tools, FastAPI upload/query endpoints and local OCR are implemented.
Manual correction/confirmation, client interfaces and reporting integrations
remain planned. GitHub Actions is configured for database, API and OCR tests.

```text
 Mobile App                  Desktop Web Interface
 React Native + Expo         React + TypeScript
 + TypeScript                + Vite + CSS
 + NativeWind                + Tailwind CSS
    |                       |
    +-----------+-----------+
                |
                v
     Python + FastAPI Backend
                |
       +--------+---------+
       |        |         |
       v        v         v
      OCR     Business   Data
   Processing   Logic   Validation
       |        |         |
       +--------+---------+
                |
                v
      SQLite + SQL Database
                |
        +-------+-------+
        |               |
        v               v
     Pandas          Power BI
    Analytics       Dashboards

    unittest + GitHub Actions
        Automated Testing
```

The planned mobile app, desktop web interface, and analytics pipeline will share the same backend logic and data model. The mobile app will support receipt photography and daily interactions. The desktop interface will use React, TypeScript, Vite, CSS, and Tailwind CSS for receipt uploads, review, and analytical views. Pandas will support data preparation and analysis, while Power BI will provide deeper analytical reporting. The Power BI integration approach will be selected during implementation.

## 3. Technology Stack

| Component | Core Technologies | Purpose |
|---|---|---|
| Mobile app | React Native + Expo + TypeScript + NativeWind | Receipt photography and daily spending management on iOS and Android |
| Desktop web interface | React + TypeScript + Vite + CSS + Tailwind CSS | Upload existing receipts and view analytics in a desktop browser; no camera workflow required |
| Backend | Python + FastAPI | Shared API, receipt processing, and business logic |
| Database | SQLite + SQL | Relational data storage and querying |
| Data analytics | Pandas + Power BI | Data preparation, spending analysis, and dashboards |

Supporting technologies and responsibilities:

| Technology | Purpose |
|---|---|
| Python | Backend processing, ETL, and business logic |
| FastAPI | Shared REST API for the mobile app and desktop web interface |
| Uvicorn | Local ASGI server for running the FastAPI backend |
| python-multipart | Multipart receipt file uploads |
| Pillow / pypdf | Validate uploaded image and PDF documents |
| React Native + Expo | Cross-platform iOS and Android application |
| React | Desktop web interface for receipt uploads, review, and analytical views |
| TypeScript | Type-safe mobile and desktop web application development |
| Vite | Desktop web development server and build tooling |
| CSS | Desktop web styling and layout |
| NativeWind | Tailwind-style utility classes for styling React Native components in the mobile app |
| Tailwind CSS | Utility-first CSS framework for styling the desktop web interface |
| RapidOCR | Implemented local text extraction from grocery receipt images |
| pypdf / pypdfium2 | Extract embedded PDF text or render scanned pages for OCR |
| OpenCV | Receipt image preprocessing |
| Pandas / NumPy | Data cleaning, transformation, and analysis |
| SQLite / SQL | Relational data storage and querying |
| Power BI / DAX / Power Query | Data modelling, dashboards, and business intelligence |
| unittest / TestClient | Database and HTTP API integration tests (TestClient uses httpx2) |
| pytest | Planned broader test tooling; can also collect the existing unittest suite |
| Git / GitHub | Version control and project collaboration |
| GitHub Actions | Automated testing and continuous integration |

NativeWind is designed for React Native, while Tailwind CSS is a CSS framework for web development. The mobile app will use NativeWind to style native components, and the desktop web interface will use Tailwind CSS to style web elements.

## 4. Data Model

The SQLite schema is implemented with **12 business tables**, one migration
metadata table, and **six analytical views**. Monetary amounts use integer minor
units, and spending views separate currencies and include only verified grocery receipts.

This database serves the grocery module only. `categories` holds grocery product
groups, and `budgets` stores grocery budgets. There is no general expense-type
field to select between grocery and other spending domains. Existing `_type`
fields describe receipt/price sources, price conditions, and quality issues.

- [Data structure](data/README.md): table fields, primary/foreign keys, analytical
  views, constraints, indexes, and legacy tables.
- [Database guide](docs/database.md): relationships, migrations, storage rules,
  and Python usage.
- [Test guide](tests/README.md): running the tests and the purpose of each test.
- [API guide](docs/api.md): backend setup, endpoints, uploads and configuration.
- [OCR guide](docs/ocr.md): local recognition, provisional extraction, setup and review workflow.
- [OCR benchmark](ocr-benchmark/README.md): isolated images, dependencies, script and instructions for comparing Tesseract, RapidOCR and PaddleOCR.

Core tables retain the original names: `Supermarket`, `Item`, `Receipt`, and
`ReceiptItem`. Related store references use `supermarket_id`, and store spending
is exposed through `v_supermarket_spending`. Existing original-layout records
are preserved in `legacy_` archive tables during the naming migration.

Initialise the local database from the repository root using Python:

```bash
python -m spending.database
```

The default location is `data/spending.db`. Initialisation is repeatable, backs
up existing databases before applying migrations, and preserves legacy tables.
See the [database guide](docs/database.md) for the schema, relationships,
validation rules, analytical views, and Python usage.

## 5. Data Quality and Testing

Data reliability is a core part of the project.

- Validate required fields, dates, monetary values, and database relationships.
- Evaluate OCR accuracy against manually verified receipt data.
- Test price calculations, discounts, and unit conversions.
- Detect duplicate records and inconsistent product matches.
- Automate tests through pytest and GitHub Actions.

Tests use Python's built-in `unittest`. Database-only tests require no extra
packages; API tests use FastAPI's TestClient and the dependencies listed in
`requirements-dev.txt`. Install these to run the full suite:

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

The latest local run passed **61 tests: 12 database, 21 API and 28 OCR/parser tests**,
including RapidOCR image, scanned-PDF and HTTP-to-database checks when the
application dependencies are installed. See
[tests/README.md](tests/README.md) for each test's scenario, expected result,
and purpose. [GitHub Actions](.github/workflows/database.yml) is configured to
run this suite on pushes and pull requests; a remote CI result has not yet been
verified. Real-receipt field-level accuracy evaluation and mobile/desktop workflow
tests remain planned; synthetic OCR checks are not an accuracy benchmark.

## 6. Development Roadmap

Current milestone: **database, receipt upload/query APIs, local OCR, and manual
review/verification completed; reporting APIs are next**.

| Area | Current progress | Remaining work |
|---|---|---|
| Database | 12 business tables, migration metadata, constraints, indexes, six views, connection helper, repeatable setup and backups implemented | Explicit legacy-data import after confirming units/currency |
| Tests and CI | 61 passing tests (12 database, 21 API, 28 OCR/parser); CI installs Python dependencies | Verify remote CI and evaluate accuracy against labelled real receipts |
| Receipt processing | Upload validation, duplicate detection, low-resolution image enlargement, local OCR, provisional fields/items, manual correction and verification implemented | Richer store-specific parsing and real-receipt accuracy evaluation |
| Backend | FastAPI health, upload/list/detail, OCR execution/result, correction and verification endpoints implemented | Grocery reporting APIs and access control |
| Mobile app | Technology stack selected | React Native/Expo interface, NativeWind styling and receipt photography |
| Desktop web | Minimal React/Vite page for upload, OCR results, review and verification implemented | Item-level editing, Tailwind CSS styling and analytical views |
| Analytics and reporting | SQL views for spending, budgets, reconciliation and price history implemented | Pandas workflows, Power BI dashboards, data refresh and integration |
| Price intelligence | Price observations and unit-price view implemented | Product matching, price ingestion, retailer comparisons and basket estimation |

- [ ] **Phase 1:** Database schema and receipt processing pipeline.
  - [x] SQLite schema, constraints, indexes and analytical views.
  - [x] Connection helper, repeatable migrations and automatic backups.
  - [x] Database tests and CI workflow configuration (remote run not yet verified).
  - [x] Receipt file ingestion, validation, duplicate detection and pending records.
  - [x] Local OCR, PDF text/rendering, provisional receipt parsing and saved OCR attempts.
  - [x] Manual correction and confirmation with an audit history.
  - [ ] Real-receipt accuracy evaluation.
- [ ] **Phase 2:** FastAPI backend and grocery expense tracking.
  - [x] FastAPI startup, health check, receipt upload/list/detail endpoints and API tests.
  - [x] OCR execution/latest-result endpoints, failure persistence and retries.
  - [x] Correction and verification endpoints.
  - [ ] Grocery reporting APIs.
- [ ] **Phase 3:** Mobile app interface and receipt scanning workflow.
- [ ] **Phase 4:** Desktop web interface for receipt uploads and review, spending analytics, and Power BI dashboards; no desktop camera workflow required.
- [ ] **Phase 5:** Product price tracking and supermarket comparison.
- [ ] **Phase 6:** Automated testing, deployment, and reliability improvements.

## 7. Privacy and Data Handling

- Keep personal receipts and financial records out of version control.
- Store uploaded receipts securely and restrict access to personal data.
- Use anonymised or synthetic data in public demonstrations.
- Review external data-source terms before collecting supermarket prices.

## 8. Project Objectives

This project demonstrates practical skills in:

- Python development and ETL pipelines.
- Relational database design and SQL analytics.
- OCR integration and human-in-the-loop data correction.
- Power BI reporting and business intelligence.
- Cross-platform mobile application development.
- Desktop web interface development for receipt uploads and analytical reporting.
- Automated testing, data quality, and continuous integration.

The goal is to build a reliable, end-to-end grocery module that transforms grocery receipts into actionable grocery spending insights and supermarket product price comparisons.

## 9. Issues and Resolutions

### 2026-10-22 — Receipt photo OCR quality

The three-image comparison found that RapidOCR produced the most consistent
usable results for photographed Tesco and Lidl receipts while also being the
fastest tested engine. The application now uses RapidOCR for image and scanned
PDF recognition. Images are still EXIF-oriented, grayscale/contrast-prepared and
enlarged when narrow; original uploads are unchanged.

The comparison remains a qualitative three-sample result, rather than a
field-level accuracy measurement. See the [benchmark analysis](ocr-benchmark/README.md#results-from-the-three-sample-receipts) for observed results and the [OCR guide](docs/ocr.md) for application behaviour.

### 2026-10-23 — Lidl prices emitted on separate lines

RapidOCR correctly recognised the Lidl receipt's text, but it emitted `TOTAL`
and `19.77` on separate lines and ordered some tax-marked prices before their
product descriptions. The generic parser expected a label and amount on the
same line, leaving the total empty and associating two weighted-price rows as
items. The parser now treats a following amount as a standalone total and pairs
Lidl's positive tax-marked price rows with nearby unused product names. The
source OCR text remains unchanged, discounts remain review warnings, and the
item/total reconciliation still requires confirmation.

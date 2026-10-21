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
local database tests. The current working implementation is the SQLite database
and its Python setup tools. OCR processing, the FastAPI API, mobile/desktop
interfaces, Pandas workflows, and Power BI dashboards are still planned.

## 1. Key Features

- **Receipt Processing:** OCR-based receipt extraction, manual correction, duplicate detection, and data validation.
- **Grocery Expense Tracking:** Monitor grocery spending by month, grocery product category, and supermarket, with optional grocery budget tracking.
- **Price Intelligence:** Track historical product prices, calculate unit prices, and compare equivalent products across supermarkets.
- **Shopping Management:** Create grocery shopping lists and estimate grocery basket costs.
- **Product Quality Log:** Record product issues and purchase-related notes.
- **Data Analytics:** Build Power BI dashboards for grocery spending trends, supermarket price analysis, and data quality monitoring.

### Desktop Workflow (Planned)

1. Upload existing receipt images or PDF files from the computer.
2. Review OCR results and correct receipt details before saving verified records.
3. View grocery spending summaries and trends, with filters for date, grocery product category, and supermarket.
4. Explore product price history and supermarket comparisons.

The mobile app supports taking receipt photos. The desktop interface focuses on file uploads and analytical views, with no receipt photography workflow.

## 2. System Architecture

The following diagram shows the target architecture. The SQLite database and
initialisation tools are implemented; the application and reporting layers are
planned. GitHub Actions is configured for the current `unittest` database suite.

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
| React Native + Expo | Cross-platform iOS and Android application |
| React | Desktop web interface for receipt uploads, review, and analytical views |
| TypeScript | Type-safe mobile and desktop web application development |
| Vite | Desktop web development server and build tooling |
| CSS | Desktop web styling and layout |
| NativeWind | Tailwind-style utility classes for styling React Native components in the mobile app |
| Tailwind CSS | Utility-first CSS framework for styling the desktop web interface |
| PaddleOCR / Tesseract | Extract text from shopping receipts |
| OpenCV | Receipt image preprocessing |
| Pandas / NumPy | Data cleaning, transformation, and analysis |
| SQLite / SQL | Relational data storage and querying |
| Power BI / DAX / Power Query | Data modelling, dashboards, and business intelligence |
| unittest | Implemented database integration and validation tests |
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

The database tests currently use Python's built-in `unittest` and require no
additional packages (they can also be collected by pytest):

```bash
python -m unittest discover -s tests -v
```

The latest local run passed all **12 database tests**. See
[tests/README.md](tests/README.md) for each test's scenario, expected result,
and purpose. [GitHub Actions](.github/workflows/database.yml) is configured to
run this suite on pushes and pull requests; a remote CI result has not yet been
verified. OCR accuracy and application workflow tests remain planned.

## 6. Development Roadmap

Current milestone: **database foundation completed; Phase 1 remains in progress**.

| Area | Current progress | Remaining work |
|---|---|---|
| Database | 12 business tables, migration metadata, constraints, indexes, six views, connection helper, repeatable setup and backups implemented | Explicit legacy-data import after confirming units/currency |
| Tests and CI | 12 local database tests passed; GitHub Actions workflow configured | Verify remote CI and add tests as application features are implemented |
| Receipt processing | Tables for uploads, OCR runs and corrections are available | File ingestion, OCR extraction, parsing, review and correction workflow |
| Backend | Python database connection/setup tools are available | FastAPI routes, upload service, business validation and access control |
| Mobile app | Technology stack selected | React Native/Expo interface, NativeWind styling and receipt photography |
| Desktop web | Technology stack and upload/analytics scope selected | React/Vite interface, Tailwind CSS styling, upload/review and analytical views |
| Analytics and reporting | SQL views for spending, budgets, reconciliation and price history implemented | Pandas workflows, Power BI dashboards, data refresh and integration |
| Price intelligence | Price observations and unit-price view implemented | Product matching, price ingestion, retailer comparisons and basket estimation |

- [ ] **Phase 1:** Database schema and receipt processing pipeline.
  - [x] SQLite schema, constraints, indexes and analytical views.
  - [x] Connection helper, repeatable migrations and automatic backups.
  - [x] Database tests and CI workflow configuration (remote run not yet verified).
  - [ ] OCR extraction and receipt processing pipeline.
- [ ] **Phase 2:** FastAPI backend and grocery expense tracking.
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

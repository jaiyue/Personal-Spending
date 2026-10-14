# Personal-Spending
A Python-based data processing and analytics platform that transforms shopping receipts and supermarket price data into structured, traceable records for personal spending analysis, product price tracking, and cross-retailer comparison.

The project combines OCR, data cleaning, relational database design, SQL analytics, Power BI visualisation, and automated testing to demonstrate an end-to-end data workflow.

> **Project status:** In development

## 1. Overview

Managing personal spending involves more than recording transaction totals. Understanding spending patterns, tracking individual product prices, and comparing supermarket prices requires reliable data collected from multiple sources.

This project aims to build a platform that extracts structured information from shopping receipts, allows users to review and correct OCR results, and stores verified purchase records in a relational database. The resulting data can be analysed using SQL and Python and visualised through Power BI dashboards.

The platform will also support supermarket price comparison using receipt-derived prices and permitted online price sources, alongside a product quality log for recording issues associated with purchased items.

### Key Objectives

- Automate receipt data extraction while retaining manual control over data accuracy.
- Build a structured and traceable database of purchases and product prices.
- Analyse monthly expenditure, category-level spending, and individual product price trends.
- Compare equivalent products across supermarkets using standardised units.
- Implement data validation and automated tests to improve data reliability.
- Demonstrate practical skills relevant to data analytics, BI, data engineering, and software testing roles.

## 2. Planned Features

### 2.1 Receipt Processing and OCR

- Upload receipt images and PDF files.
- Extract purchase dates, retailer names, product descriptions, quantities, prices, discounts, and transaction totals.
- Parse OCR output into structured receipt and item records.
- Provide a manual review and correction workflow for inaccurate or incomplete results.
- Preserve original OCR output alongside corrected data.
- Detect duplicate receipts, invalid dates, missing fields, and discrepancies between item totals and receipt totals.
- Track processing and verification status.

### 2.2 Spending Analytics

- Calculate monthly and annual expenditure.
- Analyse spending by product category and retailer.
- Track month-on-month spending changes.
- Compare actual spending against optional budgets.
- Filter transactions by date, retailer, and category.
- Identify changes in purchasing behaviour and spending patterns.

### 2.3 Product Price Tracking

- Maintain a standardised product catalogue, including brand, size, quantity, and category.
- Record product prices from receipts and supported external sources.
- Track historical prices for individual products.
- Calculate average, median, minimum, and maximum observed prices.
- Calculate unit prices, such as price per kilogram, litre, or item.
- Distinguish regular prices, promotional prices, and loyalty-card prices where the source provides this information.

### 2.4 Supermarket Price Comparison

- Compare equivalent products across retailers.
- Standardise product quantities and measurement units.
- Compare unit prices rather than relying solely on package prices.
- Record source URLs, observation timestamps, and available product specifications.
- Identify uncertain product matches and outdated price observations.
- Support shopping-basket comparisons when equivalent products can be matched reliably.

Online price collection will be implemented incrementally, prioritising permitted data sources and reliable product matching.

### 2.5 Product Quality Log

- Record product quality issues and purchase notes.
- Categorise issues such as damaged packaging, spoilage, or expiry-date concerns.
- Associate notes with products, purchases, dates, and retailers.
- Analyse recurring issues by product or category where sufficient data is available.

### 2.6 Data Quality and Automated Testing

- Validate required fields, data types, date ranges, and monetary values.
- Detect duplicate records and broken relationships.
- Test receipt parsing, monetary calculations, unit-price conversions, and data transformations.
- Test database operations and correction workflows.
- Maintain a labelled receipt test dataset for evaluating OCR output.
- Run automated tests through GitHub Actions.

## 3. System Architecture

The project follows a modular architecture that separates data ingestion, processing, storage, analytics, and testing.

```text
Receipt Images / PDFs       Online Price Sources
          |                          |
          v                          v
    Python OCR                Price Ingestion
          |                          |
          +------------+-------------+
                       |
                       v
             Data Processing & ETL
          - Text and item parsing
          - Data cleaning
          - Product standardisation
          - Unit-price calculations
          - Validation and error handling
                       |
                       v
                SQLite Database
          - Receipts and receipt items
          - Product catalogue
          - Price observations
          - Quality notes
          - OCR and correction records
                       |
             +---------+---------+
             |                   |
             v                   v
        SQL / Python         Power BI
        Analysis             Dashboards
             |
             v
       Analytical Outputs

     pytest + GitHub Actions
     Automated testing and CI
```

### Technology Stack

| Component | Technology | Purpose |
|---|---|---|
| Programming | Python | Data processing, OCR orchestration, ETL, and validation |
| OCR | PaddleOCR or Tesseract | Receipt text extraction |
| Image Processing | OpenCV | Image enhancement and preprocessing |
| Data Processing | Pandas, NumPy | Data cleaning, transformation, and analysis |
| Database | SQLite, SQL | Structured storage and analytical queries |
| Business Intelligence | Power BI, Power Query, DAX | Data modelling, measures, and dashboards |
| Testing | pytest | Unit, integration, and data validation tests |
| Version Control | Git, GitHub | Source control and project documentation |
| CI | GitHub Actions | Automated test execution |

The initial implementation is designed to run locally. Additional services or orchestration tools may be introduced if justified by the project's requirements.

## 4. Data Model

The database will use a relational structure to separate transactions, products, and price observations.

| Table | Purpose |
|---|---|
| `receipts` | Receipt metadata, retailer, purchase date, totals, and processing status |
| `receipt_items` | Individual purchased items, quantities, prices, discounts, and product references |
| `products` | Standardised product names, brands, categories, sizes, and measurement units |
| `price_observations` | Observed prices, retailers, timestamps, source URLs, and promotion details |
| `quality_notes` | Product quality observations and purchase-related notes |
| `ocr_runs` | OCR engine details, processing status, and recognition outputs |
| `correction_audit` | Original values, corrected values, and correction timestamps |

Foreign keys will be used to maintain relationships between receipts, receipt items, products, and associated records.

Original receipt descriptions and OCR outputs will be retained where appropriate to support traceability and error analysis.

## 5. Power BI Dashboards

The planned Power BI report will contain four analytical pages.

### Spending Overview
- Total expenditure and monthly spending trends.
- Category-level spending breakdown.
- Spending by retailer.
- Budget versus actual expenditure.

### Product Price Intelligence
- Historical price trends for selected products.
- Unit-price comparisons over time.
- Average, median, minimum, and maximum observed prices.
- Product and specification filters.

### Supermarket Comparison
- Side-by-side comparison of equivalent products.
- Unit-price rankings across retailers.
- Promotional and loyalty-card price distinctions.
- Estimated basket costs based on matched products.

### Data Quality and Product Issues
- Records awaiting manual correction.
- OCR field-level evaluation results.
- Invalid or incomplete price observations.
- Product quality issues by category and retailer.

Dashboard measures will be defined using DAX, with data preparation and transformation performed through SQL, Python, and Power Query as appropriate.

## 6. Data Quality and Evaluation

Data quality is a core design consideration rather than a final-stage enhancement.

Planned validation and evaluation include:

- **OCR evaluation:** Compare extracted fields against manually verified receipt data.
- **Parsing accuracy:** Assess whether product descriptions, quantities, and monetary values are assigned to the correct fields.
- **Financial validation:** Check item totals, discounts, and receipt totals while accounting for legitimate adjustments.
- **Product matching:** Prevent comparisons between products with materially different sizes, units, or specifications.
- **Data integrity:** Validate uniqueness, required fields, and database relationships.
- **Test coverage:** Exercise normal cases, invalid inputs, boundary cases, and failure scenarios.

Evaluation results will be documented with the test dataset size, metric definitions, and representative errors. Results will only be reported after the corresponding tests have been executed.

## 7. Testing Strategy

The testing strategy will cover the main processing pipeline and its critical failure points.

| Test level | Example |
|---|---|
| Unit tests | OCR text parsing, discount calculations, unit-price conversions |
| Data validation tests | Missing fields, invalid dates, duplicate receipts, negative or implausible values |
| Integration tests | Receipt processing and SQLite persistence |
| Workflow tests | Manual corrections, verification status, and audit records |
| Regression tests | Previously identified OCR parsing errors |
| Continuous integration | Run automated tests on pushes and pull requests |

The project will use pytest for automated testing and GitHub Actions for continuous integration.

## 8. Development Roadmap

- [ ] **Phase 1 — Receipt ingestion:** Database schema, OCR integration, editable receipt records, and validation.
- [ ] **Phase 2 — Spending analytics:** SQL queries, category analysis, and the initial Power BI report.
- [ ] **Phase 3 — Testing and reliability:** Automated tests, a labelled OCR evaluation dataset, error handling, and CI.
- [ ] **Phase 4 — Price intelligence:** Product standardisation, historical prices, unit-price calculations, and retailer comparisons.
- [ ] **Phase 5 — Extensions:** Permitted online price collection, quality issue analysis, and automated reporting.

The roadmap will be updated as features are implemented and validated.

## 9. Project Structure

The repository is expected to follow a structure similar to the following:

```text
personal-spending-price-intelligence/
├── src/
│   ├── ocr/
│   ├── ingestion/
│   ├── processing/
│   ├── validation/
│   ├── analytics/
│   └── database/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── sql/
├── powerbi/
├── data/
│   └── README.md
├── docs/
│   ├── data-model.md
│   ├── testing-strategy.md
│   └── data-dictionary.md
├── scripts/
├── .github/
│   └── workflows/
├── requirements.txt
├── .gitignore
└── README.md
```

This is a proposed structure and may change during implementation.

## 10. Setup and Usage

The following setup instructions are a starting point. Exact dependencies and execution commands will be documented once the implementation is established.

### Prerequisites

- Python 3.10 or a compatible version supported by the selected dependencies.
- Git.
- Power BI Desktop running in a supported Windows environment for authoring the `.pbix` report.
- A local environment for storing receipt files and the SQLite database.

### Installation

```bash
git clone <repository-url>
cd personal-spending-price-intelligence

python -m venv .venv
```

Activate the environment:

**macOS / Linux**

```bash
source .venv/bin/activate
```

**Windows PowerShell**

```powershell
.venv\Scripts\Activate.ps1
```

Install dependencies once `requirements.txt` has been defined:

```bash
pip install -r requirements.txt
```

### Running the Project

Application startup and processing commands will be added after the relevant modules are implemented.

Power BI will connect to the project's analytical data source to support report creation and refresh.

## 11. Privacy and Data Handling

Receipt images may contain sensitive information. The initial implementation will prioritise local processing and local storage.

- Avoid committing personal receipts, financial records, database files, or credentials to Git.
- Use anonymised or synthetic sample data in the public repository.
- Keep original receipt images outside version control.
- Review external data-source terms before collecting or redistributing online prices.
- Document any limitations in data availability, product matching, and price freshness.

## 12. Project Goals

This project is intended to demonstrate practical capabilities in:

- Python-based data processing and ETL.
- SQL querying and relational database design.
- Data cleaning, validation, and quality assurance.
- Power BI data modelling, DAX, and dashboard development.
- OCR integration and human-in-the-loop correction.
- Automated testing, regression testing, and continuous integration.
- Reproducible workflows and technical documentation.

**The objective is to build a reliable end-to-end data product in which raw information can be traced, validated, analysed, and presented in a form that supports practical decisions.**

-- Canonical schema for a new Personal Spending SQLite database.

-- All monetary amounts are INTEGER minor units (e.g. pence for GBP).
-- Currency codes are explicit so analytics never sum different currencies.
CREATE TABLE Supermarket (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    location TEXT NOT NULL DEFAULT '',
    store_format TEXT,
    UNIQUE (name, location)
);

CREATE TABLE Brand (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK (length(trim(name)) > 0)
);

CREATE TABLE BrandAlias (
    id INTEGER PRIMARY KEY,
    brand_id INTEGER NOT NULL REFERENCES Brand(id) ON DELETE CASCADE,
    alias TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK (length(trim(alias)) > 0)
);

CREATE TABLE categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK (length(trim(name)) > 0)
);

CREATE TABLE Item (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    brand_id INTEGER REFERENCES Brand(id) ON DELETE RESTRICT,
    category_id INTEGER REFERENCES categories(id) ON DELETE RESTRICT,
    barcode TEXT UNIQUE,
    pack_size REAL CHECK (pack_size IS NULL OR (typeof(pack_size) IN ('integer', 'real') AND pack_size > 0)),
    pack_unit TEXT CHECK (pack_unit IN ('g', 'kg', 'ml', 'l', 'item')),
    CHECK ((pack_size IS NULL) = (pack_unit IS NULL))
);

-- Common UK grocery brands. INSERT OR IGNORE keeps setup repeatable.
INSERT OR IGNORE INTO Brand(name) VALUES
  ('Aunt Bessie''s'), ('Bakers'), ('Batchelors'), ('Baxters'), ('Belvita'),
  ('Ben & Jerry''s'), ('Birds Eye'), ('Bisto'), ('Bonne Maman'), ('Branston'),
  ('Cadbury'), ('Campbell''s'), ('Cathedral City'), ('Coca-Cola'), ('Colgate'),
  ('Comfort'), ('Cornetto'), ('Costa Coffee'), ('Cow & Gate'), ('Cussons'),
  ('Danone'), ('Denny'), ('Dettol'), ('Digestives'), ('Dole'), ('Dorset Cereals'),
  ('Dr. Oetker'), ('Dove'), ('Duracell'), ('E45'), ('Ecover'), ('Elmlea'),
  ('Fairy'), ('Felix'), ('Fever-Tree'), ('Flora'), ('Fox''s'), ('Fray Bentos'),
  ('Galaxy'), ('Garnier'), ('Gillette'), ('Green & Black''s'), ('Greggs'),
  ('Haribo'), ('Heinz'), ('Hellmann''s'), ('Hovis'), ('HP'), ('Innocent'),
  ('Jacobs'), ('John West'), ('Kellogg''s'), ('Kenco'), ('King''smill'),
  ('Knorr'), ('Lactofree'), ('Lays'), ('Lenor'), ('Lindt'), ('Lipton'),
  ('Lurpak'), ('Lynx'), ('Mackie''s'), ('Maltesers'), ('Mars'), ('McCain'),
  ('McVitie''s'), ('Müller'), ('Nando''s'), ('Nescafé'), ('Nestlé'), ('Nutella'),
  ('Oatly'), ('Old El Paso'), ('Oreo'), ('Pampers'), ('Panadol'), ('Pepsi'),
  ('Persil'), ('PG Tips'), ('Philadelphia'), ('Pledge'), ('Pot Noodle'),
  ('Pringles'), ('Purina'), ('Quality Street'), ('Quaker'), ('Ribena'),
  ('Robinsons'), ('Rowntree''s'), ('Sainsbury''s'), ('Schweppes'), ('Sharwood''s'),
  ('Sheba'), ('Simple'), ('Skittles'), ('Stella Artois'), ('Stork'), ('Tetley'),
  ('The Collective'), ('Tilda'), ('Twinings'), ('Tyrrells'), ('Uncle Ben''s'),
  ('Vaseline'), ('Walkers'), ('Warburtons'), ('Weetabix'), ('Whiskas'), ('Wilkinson Sword'),
  ('Wotsits'), ('Yeo Valley'), ('Yorkshire Tea'),
  ('Aldi'), ('Asda'), ('Co-op'), ('Iceland'), ('Lidl'), ('M&S'), ('Morrisons'), ('Ocado'), ('Tesco'), ('Waitrose');

-- Common printed or OCR variants map back to one canonical brand.
INSERT OR IGNORE INTO BrandAlias(brand_id, alias)
SELECT id, 'Marks & Spencer' FROM Brand WHERE name = 'M&S'
UNION ALL SELECT id, 'M and S' FROM Brand WHERE name = 'M&S'
UNION ALL SELECT id, 'Coke' FROM Brand WHERE name = 'Coca-Cola'
UNION ALL SELECT id, 'Coca Cola' FROM Brand WHERE name = 'Coca-Cola'
UNION ALL SELECT id, 'Kelloggs' FROM Brand WHERE name = 'Kellogg''s'
UNION ALL SELECT id, 'McVities' FROM Brand WHERE name = 'McVitie''s'
UNION ALL SELECT id, 'Sainsburys' FROM Brand WHERE name = 'Sainsbury''s'
UNION ALL SELECT id, 'Green and Black''s' FROM Brand WHERE name = 'Green & Black''s';

-- Partial OCR output is allowed here; verified Receipt require core fields.
CREATE TABLE Receipt (
    id INTEGER PRIMARY KEY,
    supermarket_id INTEGER REFERENCES Supermarket(id) ON DELETE RESTRICT,
    purchase_date TEXT CHECK (
        purchase_date IS NULL OR
        (length(purchase_date) = 10 AND date(purchase_date, '+0 days') IS NOT NULL
         AND date(purchase_date, '+0 days') = purchase_date)
    ),
    currency TEXT NOT NULL DEFAULT 'GBP'
        CHECK (length(currency) = 3 AND currency NOT GLOB '*[^A-Z]*'),
    total_pence INTEGER CHECK (total_pence IS NULL OR (typeof(total_pence) = 'integer' AND total_pence >= 0)),
    discount_pence INTEGER NOT NULL DEFAULT 0
        CHECK (typeof(discount_pence) = 'integer' AND discount_pence >= 0),
    voucher_pence INTEGER NOT NULL DEFAULT 0
        CHECK (typeof(voucher_pence) = 'integer' AND voucher_pence >= 0),
    adjustment_pence INTEGER NOT NULL DEFAULT 0
        CHECK (typeof(adjustment_pence) = 'integer'),
    source_path TEXT,
    file_sha256 TEXT UNIQUE CHECK (file_sha256 IS NULL OR
        (length(file_sha256) = 64 AND file_sha256 NOT GLOB '*[^0-9a-f]*')),
    source_type TEXT NOT NULL DEFAULT 'upload'
        CHECK (source_type IN ('upload', 'camera', 'manual')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'needs_review', 'verified', 'failed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (status <> 'verified' OR
        (supermarket_id IS NOT NULL AND purchase_date IS NOT NULL AND total_pence IS NOT NULL))
);

CREATE TABLE ReceiptItem (
    id INTEGER PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES Receipt(id) ON DELETE RESTRICT,
    line_number INTEGER NOT NULL CHECK (line_number > 0),
    product_id INTEGER REFERENCES Item(id) ON DELETE RESTRICT,
    category_id INTEGER REFERENCES categories(id) ON DELETE RESTRICT,
    raw_description TEXT NOT NULL CHECK (length(trim(raw_description)) > 0),
    quantity REAL NOT NULL DEFAULT 1 CHECK (typeof(quantity) IN ('integer', 'real') AND quantity > 0),
    unit_price_pence INTEGER CHECK (unit_price_pence IS NULL OR (typeof(unit_price_pence) = 'integer' AND unit_price_pence >= 0)),
    discount_pence INTEGER NOT NULL DEFAULT 0
        CHECK (typeof(discount_pence) = 'integer' AND discount_pence >= 0),
    original_pence INTEGER NOT NULL
        CHECK (typeof(original_pence) = 'integer' AND original_pence >= 0),
    UNIQUE (receipt_id, line_number),
    UNIQUE (id, receipt_id)
);

CREATE TABLE ocr_runs (
    id INTEGER PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES Receipt(id) ON DELETE RESTRICT,
    engine TEXT NOT NULL CHECK (length(trim(engine)) > 0),
    engine_version TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    raw_output TEXT,
    confidence REAL CHECK (confidence >= 0 AND confidence <= 1),
    error_message TEXT,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    completed_at TEXT,
    UNIQUE (id, receipt_id)
);

CREATE TABLE correction_audit (
    id INTEGER PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES Receipt(id) ON DELETE RESTRICT,
    receipt_item_id INTEGER,
    ocr_run_id INTEGER,
    field_name TEXT NOT NULL CHECK (length(trim(field_name)) > 0),
    original_value TEXT,
    corrected_value TEXT,
    corrected_by TEXT,
    corrected_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (receipt_item_id, receipt_id) REFERENCES ReceiptItem(id, receipt_id) ON DELETE RESTRICT,
    FOREIGN KEY (ocr_run_id, receipt_id) REFERENCES ocr_runs(id, receipt_id) ON DELETE RESTRICT
);

CREATE TABLE price_observations (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES Item(id) ON DELETE RESTRICT,
    supermarket_id INTEGER NOT NULL REFERENCES Supermarket(id) ON DELETE RESTRICT,
    receipt_item_id INTEGER REFERENCES ReceiptItem(id) ON DELETE RESTRICT,
    price_pence INTEGER NOT NULL CHECK (typeof(price_pence) = 'integer' AND price_pence >= 0),
    currency TEXT NOT NULL DEFAULT 'GBP'
        CHECK (length(currency) = 3 AND currency NOT GLOB '*[^A-Z]*'),
    -- Snapshot sizes so later catalogue changes do not rewrite price history.
    pack_size REAL CHECK (pack_size IS NULL OR (typeof(pack_size) IN ('integer', 'real') AND pack_size > 0)),
    pack_unit TEXT CHECK (pack_unit IN ('g', 'kg', 'ml', 'l', 'item')),
    price_type TEXT NOT NULL DEFAULT 'regular'
        CHECK (price_type IN ('regular', 'promotion', 'loyalty')),
    source_type TEXT NOT NULL CHECK (source_type IN ('receipt', 'online', 'manual')),
    source_url TEXT,
    observed_at TEXT NOT NULL CHECK (julianday(observed_at) IS NOT NULL),
    CHECK ((pack_size IS NULL) = (pack_unit IS NULL)),
    CHECK (source_type <> 'receipt' OR receipt_item_id IS NOT NULL),
    CHECK (source_type <> 'online' OR length(trim(coalesce(source_url, ''))) > 0)
);

CREATE TABLE quality_notes (
    id INTEGER PRIMARY KEY,
    product_id INTEGER REFERENCES Item(id) ON DELETE RESTRICT,
    receipt_id INTEGER REFERENCES Receipt(id) ON DELETE RESTRICT,
    receipt_item_id INTEGER,
    issue_type TEXT NOT NULL DEFAULT 'other'
        CHECK (issue_type IN ('packaging', 'spoilage', 'expiry', 'other')),
    note TEXT NOT NULL CHECK (length(trim(note)) > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (product_id IS NOT NULL OR receipt_id IS NOT NULL),
    CHECK (receipt_item_id IS NULL OR receipt_id IS NOT NULL),
    FOREIGN KEY (receipt_item_id, receipt_id) REFERENCES ReceiptItem(id, receipt_id) ON DELETE RESTRICT
);

CREATE TABLE shopping_lists (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'archived')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE shopping_list_items (
    id INTEGER PRIMARY KEY,
    shopping_list_id INTEGER NOT NULL REFERENCES shopping_lists(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES Item(id) ON DELETE RESTRICT,
    description TEXT NOT NULL CHECK (length(trim(description)) > 0),
    quantity REAL NOT NULL DEFAULT 1 CHECK (typeof(quantity) IN ('integer', 'real') AND quantity > 0),
    purchased INTEGER NOT NULL DEFAULT 0 CHECK (purchased IN (0, 1))
);

CREATE TABLE budgets (
    id INTEGER PRIMARY KEY,
    month TEXT NOT NULL CHECK (length(month) = 7 AND
        date(month || '-01', '+0 days') IS NOT NULL AND
        strftime('%Y-%m', month || '-01') = month),
    category_id INTEGER REFERENCES categories(id) ON DELETE RESTRICT,
    currency TEXT NOT NULL DEFAULT 'GBP'
        CHECK (length(currency) = 3 AND currency NOT GLOB '*[^A-Z]*'),
    amount_pence INTEGER NOT NULL CHECK (typeof(amount_pence) = 'integer' AND amount_pence >= 0)
);
CREATE UNIQUE INDEX budgets_category_unique ON budgets(month, category_id, currency)
    WHERE category_id IS NOT NULL;
CREATE UNIQUE INDEX budgets_overall_unique ON budgets(month, currency)
    WHERE category_id IS NULL;

CREATE INDEX receipt_date_supermarket ON Receipt(purchase_date, supermarket_id);
CREATE INDEX receipts_status ON Receipt(status);
CREATE INDEX receipt_items_product ON ReceiptItem(product_id);
CREATE INDEX receipt_items_category ON ReceiptItem(category_id);
CREATE INDEX products_category ON Item(category_id);
CREATE INDEX brand_aliases_brand ON BrandAlias(brand_id);
CREATE INDEX ocr_runs_receipt ON ocr_runs(receipt_id);
CREATE INDEX correction_audit_receipt ON correction_audit(receipt_id);
CREATE INDEX price_observations_history ON price_observations(product_id, supermarket_id, currency, observed_at);
CREATE INDEX price_observations_item ON price_observations(receipt_item_id);
CREATE INDEX quality_notes_product ON quality_notes(product_id);
CREATE INDEX quality_notes_receipt ON quality_notes(receipt_id);
CREATE INDEX shopping_list_items_list ON shopping_list_items(shopping_list_id);

CREATE VIEW v_monthly_spending AS
SELECT substr(purchase_date, 1, 7) AS month, currency,
       count(*) AS receipt_count, sum(total_pence) AS total_pence
FROM Receipt WHERE status = 'verified'
GROUP BY substr(purchase_date, 1, 7), currency;

CREATE VIEW v_supermarket_spending AS
SELECT substr(r.purchase_date, 1, 7) AS month, r.currency,
       r.supermarket_id, s.name AS supermarket_name,
       count(*) AS receipt_count, sum(r.total_pence) AS total_pence
FROM Receipt r JOIN Supermarket s ON s.id = r.supermarket_id
WHERE r.status = 'verified'
GROUP BY substr(r.purchase_date, 1, 7), r.currency, r.supermarket_id;

-- Receipt-level discounts/adjustments are NOT allocated across categories.
CREATE VIEW v_category_spending AS
SELECT substr(r.purchase_date, 1, 7) AS month, r.currency,
       coalesce(i.category_id, p.category_id) AS category_id,
       coalesce(c.name, 'Uncategorised') AS category_name,
       sum(i.original_pence - i.discount_pence) AS total_pence
FROM ReceiptItem i JOIN Receipt r ON r.id = i.receipt_id
LEFT JOIN Item p ON p.id = i.product_id
LEFT JOIN categories c ON c.id = coalesce(i.category_id, p.category_id)
WHERE r.status = 'verified'
GROUP BY substr(r.purchase_date, 1, 7), r.currency, coalesce(i.category_id, p.category_id);

CREATE VIEW v_receipt_reconciliation AS
SELECT r.id AS receipt_id, r.currency, r.status, r.total_pence,
       count(i.id) AS item_count,
       coalesce(sum(i.original_pence - i.discount_pence), 0) AS items_total_pence,
       coalesce(sum(i.original_pence - i.discount_pence), 0) - r.voucher_pence + r.adjustment_pence AS expected_total_pence,
       r.total_pence - (coalesce(sum(i.original_pence - i.discount_pence), 0) - r.voucher_pence + r.adjustment_pence) AS difference_pence
FROM Receipt r LEFT JOIN ReceiptItem i ON i.receipt_id = r.id
GROUP BY r.id;

CREATE VIEW v_product_price_history AS
SELECT o.*, p.name AS product_name, s.name AS supermarket_name,
       CASE o.pack_unit WHEN 'g' THEN 'kg' WHEN 'ml' THEN 'l' ELSE o.pack_unit END AS unit_basis,
       CASE WHEN o.pack_size IS NULL THEN NULL
            WHEN o.pack_unit IN ('g', 'ml') THEN o.price_pence * 1000.0 / o.pack_size
            ELSE o.price_pence * 1.0 / o.pack_size END AS unit_price_pence
FROM price_observations o
JOIN Item p ON p.id = o.product_id
JOIN Supermarket s ON s.id = o.supermarket_id;

CREATE VIEW v_budget_vs_actual AS
SELECT b.*, CASE WHEN b.category_id IS NULL THEN coalesce(m.total_pence, 0)
                ELSE coalesce(c.total_pence, 0) END AS actual_pence,
       b.amount_pence - CASE WHEN b.category_id IS NULL THEN coalesce(m.total_pence, 0)
                            ELSE coalesce(c.total_pence, 0) END AS remaining_pence
FROM budgets b
LEFT JOIN v_monthly_spending m ON m.month = b.month AND m.currency = b.currency
LEFT JOIN v_category_spending c ON c.month = b.month AND c.currency = b.currency
                              AND c.category_id = b.category_id;

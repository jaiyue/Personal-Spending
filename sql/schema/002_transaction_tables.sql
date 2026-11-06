-- Partial OCR output is allowed here; verified Receipt require core fields.
CREATE TABLE Receipt (
    id INTEGER PRIMARY KEY,
    supermarket_id INTEGER REFERENCES Supermarket(id) ON DELETE RESTRICT,
    expense_category_id INTEGER REFERENCES ExpenseCategory(id) ON DELETE RESTRICT,
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

-- A printed multi-buy/loyalty marker can apply to several receipt lines.
CREATE TABLE PromotionGroup (
    id INTEGER PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES Receipt(id) ON DELETE RESTRICT,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    marker_text TEXT NOT NULL CHECK (length(trim(marker_text)) > 0),
    advertised_quantity INTEGER CHECK (advertised_quantity IS NULL OR advertised_quantity > 0),
    advertised_price_pence INTEGER NOT NULL
        CHECK (typeof(advertised_price_pence) = 'integer' AND advertised_price_pence >= 0),
    UNIQUE (receipt_id, sequence),
    UNIQUE (id, receipt_id)
);

CREATE TABLE ReceiptItemPromotionGroup (
    promotion_group_id INTEGER NOT NULL,
    receipt_item_id INTEGER NOT NULL,
    receipt_id INTEGER NOT NULL,
    PRIMARY KEY (promotion_group_id, receipt_item_id),
    FOREIGN KEY (promotion_group_id, receipt_id)
        REFERENCES PromotionGroup(id, receipt_id) ON DELETE RESTRICT,
    FOREIGN KEY (receipt_item_id, receipt_id)
        REFERENCES ReceiptItem(id, receipt_id) ON DELETE RESTRICT
);

-- Keep every OCR discount separately; ReceiptItem.discount_pence is its aggregate.
CREATE TABLE ItemDiscount (
    id INTEGER PRIMARY KEY,
    receipt_item_id INTEGER NOT NULL,
    receipt_id INTEGER NOT NULL,
    promotion_group_id INTEGER,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    amount_pence INTEGER NOT NULL
        CHECK (typeof(amount_pence) = 'integer' AND amount_pence >= 0),
    reason TEXT,
    source_text TEXT NOT NULL CHECK (length(trim(source_text)) > 0),
    UNIQUE (receipt_item_id, sequence),
    FOREIGN KEY (receipt_item_id, receipt_id)
        REFERENCES ReceiptItem(id, receipt_id) ON DELETE RESTRICT,
    FOREIGN KEY (promotion_group_id, receipt_id)
        REFERENCES PromotionGroup(id, receipt_id) ON DELETE RESTRICT
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

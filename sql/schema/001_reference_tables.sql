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

-- Receipt-level categories cover all personal spending. `categories` remains
-- the more detailed product category catalogue used for item lines.
CREATE TABLE ExpenseCategory (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK (length(trim(name)) > 0)
);

CREATE TABLE MerchantExpenseCategory (
    merchant_name TEXT PRIMARY KEY COLLATE NOCASE CHECK (length(trim(merchant_name)) > 0),
    expense_category_id INTEGER NOT NULL REFERENCES ExpenseCategory(id) ON DELETE RESTRICT
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

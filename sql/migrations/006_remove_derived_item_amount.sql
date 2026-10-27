DROP VIEW IF EXISTS v_category_spending;
DROP VIEW IF EXISTS v_receipt_reconciliation;

PRAGMA foreign_keys = OFF;

CREATE TABLE ReceiptItem_new (
    id INTEGER PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES Receipt(id) ON DELETE RESTRICT,
    line_number INTEGER NOT NULL CHECK (line_number > 0),
    product_id INTEGER REFERENCES Item(id) ON DELETE RESTRICT,
    category_id INTEGER REFERENCES categories(id) ON DELETE RESTRICT,
    raw_description TEXT NOT NULL CHECK (length(trim(raw_description)) > 0),
    quantity REAL NOT NULL DEFAULT 1
        CHECK (typeof(quantity) IN ('integer', 'real') AND quantity > 0),
    unit_price_pence INTEGER
        CHECK (unit_price_pence IS NULL OR (typeof(unit_price_pence) = 'integer' AND unit_price_pence >= 0)),
    discount_pence INTEGER NOT NULL DEFAULT 0
        CHECK (typeof(discount_pence) = 'integer' AND discount_pence >= 0),
    original_pence INTEGER NOT NULL
        CHECK (typeof(original_pence) = 'integer' AND original_pence >= 0),
    UNIQUE (receipt_id, line_number),
    UNIQUE (id, receipt_id)
);

INSERT INTO ReceiptItem_new (
    id, receipt_id, line_number, product_id, category_id, raw_description,
    quantity, unit_price_pence, discount_pence, original_pence
)
SELECT id, receipt_id, line_number, product_id, category_id, raw_description,
       quantity, unit_price_pence, discount_pence, original_pence
FROM ReceiptItem;

DROP TABLE ReceiptItem;
ALTER TABLE ReceiptItem_new RENAME TO ReceiptItem;
CREATE INDEX receipt_items_product ON ReceiptItem(product_id);
CREATE INDEX receipt_items_category ON ReceiptItem(category_id);

PRAGMA foreign_keys = ON;

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

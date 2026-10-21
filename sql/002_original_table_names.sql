-- Reuse original names while retaining migration 001 for checksum verification.
-- database.py archives recognised original layouts before this migration.
DROP VIEW v_budget_vs_actual;
DROP VIEW v_product_price_history;
DROP VIEW v_receipt_reconciliation;
DROP VIEW v_category_spending;
DROP VIEW v_retailer_spending;
DROP VIEW v_monthly_spending;

ALTER TABLE retailers RENAME TO Supermarket;
ALTER TABLE products RENAME TO Item;
ALTER TABLE receipts RENAME TO Receipt;
ALTER TABLE receipt_items RENAME TO ReceiptItem;

ALTER TABLE Receipt RENAME COLUMN retailer_id TO supermarket_id;
ALTER TABLE price_observations RENAME COLUMN retailer_id TO supermarket_id;

DROP INDEX receipts_date_retailer;
CREATE INDEX receipt_date_supermarket ON Receipt(purchase_date, supermarket_id);

CREATE VIEW v_monthly_spending AS
SELECT substr(purchase_date, 1, 7) AS month, currency,
       count(*) AS receipt_count, sum(total_minor) AS total_minor
FROM Receipt WHERE status = 'verified'
GROUP BY substr(purchase_date, 1, 7), currency;

CREATE VIEW v_supermarket_spending AS
SELECT substr(r.purchase_date, 1, 7) AS month, r.currency,
       r.supermarket_id, s.name AS supermarket_name,
       count(*) AS receipt_count, sum(r.total_minor) AS total_minor
FROM Receipt r JOIN Supermarket s ON s.id = r.supermarket_id
WHERE r.status = 'verified'
GROUP BY substr(r.purchase_date, 1, 7), r.currency, r.supermarket_id;

-- Item-level discounts are already included in line_total_minor.
-- Receipt-level discounts/adjustments are NOT allocated across categories.
CREATE VIEW v_category_spending AS
SELECT substr(r.purchase_date, 1, 7) AS month, r.currency,
       coalesce(i.category_id, p.category_id) AS category_id,
       coalesce(c.name, 'Uncategorised') AS category_name,
       sum(i.line_total_minor) AS total_minor
FROM ReceiptItem i JOIN Receipt r ON r.id = i.receipt_id
LEFT JOIN Item p ON p.id = i.product_id
LEFT JOIN categories c ON c.id = coalesce(i.category_id, p.category_id)
WHERE r.status = 'verified'
GROUP BY substr(r.purchase_date, 1, 7), r.currency, coalesce(i.category_id, p.category_id);

CREATE VIEW v_receipt_reconciliation AS
SELECT r.id AS receipt_id, r.currency, r.status, r.total_minor,
       count(i.id) AS item_count,
       coalesce(sum(i.line_total_minor), 0) AS items_total_minor,
       coalesce(sum(i.line_total_minor), 0) - r.discount_minor + r.adjustment_minor AS expected_total_minor,
       r.total_minor - (coalesce(sum(i.line_total_minor), 0) - r.discount_minor + r.adjustment_minor) AS difference_minor
FROM Receipt r LEFT JOIN ReceiptItem i ON i.receipt_id = r.id
GROUP BY r.id;

CREATE VIEW v_product_price_history AS
SELECT o.*, p.name AS product_name, s.name AS supermarket_name,
       CASE o.pack_unit WHEN 'g' THEN 'kg' WHEN 'ml' THEN 'l' ELSE o.pack_unit END AS unit_basis,
       CASE WHEN o.pack_size IS NULL THEN NULL
            WHEN o.pack_unit IN ('g', 'ml') THEN o.price_minor * 1000.0 / o.pack_size
            ELSE o.price_minor * 1.0 / o.pack_size END AS unit_price_minor
FROM price_observations o
JOIN Item p ON p.id = o.product_id
JOIN Supermarket s ON s.id = o.supermarket_id;

CREATE VIEW v_budget_vs_actual AS
SELECT b.*, CASE WHEN b.category_id IS NULL THEN coalesce(m.total_minor, 0)
                ELSE coalesce(c.total_minor, 0) END AS actual_minor,
       b.amount_minor - CASE WHEN b.category_id IS NULL THEN coalesce(m.total_minor, 0)
                            ELSE coalesce(c.total_minor, 0) END AS remaining_minor
FROM budgets b
LEFT JOIN v_monthly_spending m ON m.month = b.month AND m.currency = b.currency
LEFT JOIN v_category_spending c ON c.month = b.month AND c.currency = b.currency
                              AND c.category_id = b.category_id;

ALTER TABLE Receipt RENAME COLUMN total_minor TO total_pence;
ALTER TABLE Receipt RENAME COLUMN discount_minor TO discount_pence;
ALTER TABLE Receipt RENAME COLUMN voucher_minor TO voucher_pence;
ALTER TABLE Receipt RENAME COLUMN adjustment_minor TO adjustment_pence;
ALTER TABLE ReceiptItem RENAME COLUMN unit_price_minor TO unit_price_pence;
ALTER TABLE ReceiptItem RENAME COLUMN discount_minor TO discount_pence;
ALTER TABLE ReceiptItem RENAME COLUMN original_total_minor TO original_pence;
ALTER TABLE ReceiptItem RENAME COLUMN line_total_minor TO after_discount_pence;
ALTER TABLE price_observations RENAME COLUMN price_minor TO price_pence;
ALTER TABLE budgets RENAME COLUMN amount_minor TO amount_pence;

DROP VIEW v_monthly_spending;
DROP VIEW v_supermarket_spending;
DROP VIEW v_category_spending;
DROP VIEW v_receipt_reconciliation;

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

CREATE VIEW v_category_spending AS
SELECT substr(r.purchase_date, 1, 7) AS month, r.currency,
       coalesce(i.category_id, p.category_id) AS category_id,
       coalesce(c.name, 'Uncategorised') AS category_name,
       sum(i.after_discount_pence) AS total_pence
FROM ReceiptItem i JOIN Receipt r ON r.id = i.receipt_id
LEFT JOIN Item p ON p.id = i.product_id
LEFT JOIN categories c ON c.id = coalesce(i.category_id, p.category_id)
WHERE r.status = 'verified'
GROUP BY substr(r.purchase_date, 1, 7), r.currency, coalesce(i.category_id, p.category_id);

CREATE VIEW v_receipt_reconciliation AS
SELECT r.id AS receipt_id, r.currency, r.status, r.total_pence,
       count(i.id) AS item_count,
       coalesce(sum(i.after_discount_pence), 0) AS items_total_pence,
       coalesce(sum(i.after_discount_pence), 0) - r.voucher_pence + r.adjustment_pence AS expected_total_pence,
       r.total_pence - (coalesce(sum(i.after_discount_pence), 0) - r.voucher_pence + r.adjustment_pence) AS difference_pence
FROM Receipt r LEFT JOIN ReceiptItem i ON i.receipt_id = r.id
GROUP BY r.id;

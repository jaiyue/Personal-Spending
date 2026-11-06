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

CREATE VIEW v_expense_category_spending AS
SELECT substr(r.purchase_date, 1, 7) AS month, r.currency,
       r.expense_category_id, coalesce(c.name, 'Uncategorised') AS expense_category_name,
       count(*) AS receipt_count, sum(r.total_pence) AS total_pence
FROM Receipt r LEFT JOIN ExpenseCategory c ON c.id=r.expense_category_id
WHERE r.status = 'verified'
GROUP BY substr(r.purchase_date, 1, 7), r.currency, r.expense_category_id;

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

ALTER TABLE ReceiptItem ADD COLUMN original_total_minor INTEGER NOT NULL DEFAULT 0
    CHECK (typeof(original_total_minor) = 'integer' AND original_total_minor >= 0);

UPDATE ReceiptItem
SET original_total_minor=line_total_minor,
    line_total_minor=max(line_total_minor - discount_minor, 0);

DROP VIEW v_receipt_reconciliation;

CREATE VIEW v_receipt_reconciliation AS
SELECT r.id AS receipt_id, r.currency, r.status, r.total_minor,
       count(i.id) AS item_count,
       coalesce(sum(i.line_total_minor), 0) AS items_total_minor,
       coalesce(sum(i.line_total_minor), 0) - r.voucher_minor + r.adjustment_minor AS expected_total_minor,
       r.total_minor - (coalesce(sum(i.line_total_minor), 0) - r.voucher_minor + r.adjustment_minor) AS difference_minor
FROM Receipt r LEFT JOIN ReceiptItem i ON i.receipt_id = r.id
GROUP BY r.id;

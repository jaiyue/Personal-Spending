CREATE UNIQUE INDEX budgets_category_unique ON budgets(month, category_id, currency)
    WHERE category_id IS NOT NULL;
CREATE UNIQUE INDEX budgets_overall_unique ON budgets(month, currency)
    WHERE category_id IS NULL;

CREATE INDEX receipt_date_supermarket ON Receipt(purchase_date, supermarket_id);
CREATE INDEX receipts_expense_category ON Receipt(expense_category_id);
CREATE INDEX receipts_status ON Receipt(status);
CREATE INDEX receipt_items_product ON ReceiptItem(product_id);
CREATE INDEX receipt_items_category ON ReceiptItem(category_id);
CREATE INDEX promotion_groups_receipt ON PromotionGroup(receipt_id);
CREATE INDEX receipt_item_promotions_item ON ReceiptItemPromotionGroup(receipt_item_id);
CREATE INDEX item_discounts_item ON ItemDiscount(receipt_item_id);
CREATE INDEX item_discounts_group ON ItemDiscount(promotion_group_id);
CREATE INDEX products_category ON Item(category_id);
CREATE INDEX brand_aliases_brand ON BrandAlias(brand_id);
CREATE INDEX ocr_runs_receipt ON ocr_runs(receipt_id);
CREATE INDEX correction_audit_receipt ON correction_audit(receipt_id);
CREATE INDEX price_observations_history ON price_observations(product_id, supermarket_id, currency, observed_at);
CREATE INDEX price_observations_item ON price_observations(receipt_item_id);
CREATE INDEX quality_notes_product ON quality_notes(product_id);
CREATE INDEX quality_notes_receipt ON quality_notes(receipt_id);
CREATE INDEX shopping_list_items_list ON shopping_list_items(shopping_list_id);

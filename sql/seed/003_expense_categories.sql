INSERT OR IGNORE INTO ExpenseCategory(name) VALUES
  ('Groceries'), ('Health & Beauty'), ('Dining & Takeaway'), ('Clothing'),
  ('Household'), ('Transport'), ('Entertainment'), ('Utilities'), ('Travel'),
  ('Education'), ('Gifts & Charity'), ('Other');

-- Recognised grocery retailers default to the receipt-level Groceries category.
INSERT OR IGNORE INTO MerchantExpenseCategory(merchant_name, expense_category_id)
SELECT merchant_name, e.id FROM (
    SELECT 'Tesco' AS merchant_name UNION ALL SELECT 'Sainsbury''s'
    UNION ALL SELECT 'Aldi' UNION ALL SELECT 'Lidl' UNION ALL SELECT 'Asda'
    UNION ALL SELECT 'Morrisons' UNION ALL SELECT 'Waitrose' UNION ALL SELECT 'M&S'
    UNION ALL SELECT 'Co-op' UNION ALL SELECT 'Iceland' UNION ALL SELECT 'Ocado'
) merchants CROSS JOIN ExpenseCategory e WHERE e.name = 'Groceries';

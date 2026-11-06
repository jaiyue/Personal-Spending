# Pandas analytics export

This ETL reads only `verified` receipts from SQLite and writes CSV tables
for Power BI. It never updates OCR output, review data, Items, or receipts.

```bash
python -m analytics.export --database data/spending.db --output data/analytics
```

The output directory contains:

- `receipts.csv`: receipt-level totals, discounts, vouchers, adjustments and supermarket details.
- `receipt_items.csv`: item-level OCR/review values, product, brand and category data. `net_pence` is `original_pence - discount_pence`; receipt vouchers are not allocated to categories.
- `monthly_spending.csv`: verified receipt totals by month and currency.
- `category_spending.csv`: verified item net spending by month, currency and category.
- `supermarket_spending.csv`: verified receipt totals by month, currency and supermarket.
- `expense_category_spending.csv`: verified receipt totals by month, currency and receipt-level expense category.

In Power BI, use **Get data → Text/CSV** for these files, preserve pence as
integer values, then create a measure such as `Amount GBP = SUM(total_pence) / 100`.
Refresh the export after verifying new receipts, then refresh the Power BI data.

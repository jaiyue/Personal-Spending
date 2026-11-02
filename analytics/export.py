"""Export verified grocery records as Power BI-ready CSV tables."""

import argparse
from pathlib import Path
import sqlite3

import pandas as pd

from spending.database import DEFAULT_DATABASE

EXPORTS = (
    'receipts', 'receipt_items', 'monthly_spending', 'category_spending',
    'supermarket_spending',
)


def _query(connection: sqlite3.Connection, statement: str, columns: list[str]) -> pd.DataFrame:
    """Read a query and retain its documented columns when it has no rows."""
    frame = pd.read_sql_query(statement, connection)
    return frame.reindex(columns=columns)


def export_verified_data(database_path: Path = DEFAULT_DATABASE, output_dir: Path = Path('data/analytics')) -> dict[str, Path]:
    """Write clean analysis tables from verified receipts without changing SQLite."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        receipts = _query(connection, '''
            SELECT r.id AS receipt_id, r.purchase_date, substr(r.purchase_date, 1, 7) AS month,
                   r.currency, r.total_pence, r.discount_pence, r.voucher_pence,
                   r.adjustment_pence, s.id AS supermarket_id, s.name AS supermarket_name,
                   s.location AS supermarket_location
            FROM Receipt r JOIN Supermarket s ON s.id=r.supermarket_id
            WHERE r.status='verified'
            ORDER BY r.purchase_date, r.id
        ''', ['receipt_id', 'purchase_date', 'month', 'currency', 'total_pence',
              'discount_pence', 'voucher_pence', 'adjustment_pence', 'supermarket_id',
              'supermarket_name', 'supermarket_location'])
        items = _query(connection, '''
            SELECT ri.id AS receipt_item_id, r.id AS receipt_id, r.purchase_date,
                   substr(r.purchase_date, 1, 7) AS month, r.currency,
                   s.id AS supermarket_id, s.name AS supermarket_name,
                   ri.line_number, ri.raw_description, ri.quantity,
                   ri.unit_price_pence, ri.original_pence, ri.discount_pence,
                   ri.original_pence-ri.discount_pence AS net_pence,
                   i.id AS item_id, i.name AS item_name, b.id AS brand_id,
                   b.name AS brand_name, coalesce(ri.category_id, i.category_id) AS category_id,
                   coalesce(c.name, 'Uncategorised') AS category_name,
                   i.pack_size, i.pack_unit
            FROM ReceiptItem ri JOIN Receipt r ON r.id=ri.receipt_id
            JOIN Supermarket s ON s.id=r.supermarket_id
            LEFT JOIN Item i ON i.id=ri.product_id
            LEFT JOIN Brand b ON b.id=i.brand_id
            LEFT JOIN categories c ON c.id=coalesce(ri.category_id, i.category_id)
            WHERE r.status='verified'
            ORDER BY r.purchase_date, r.id, ri.line_number
        ''', ['receipt_item_id', 'receipt_id', 'purchase_date', 'month', 'currency',
              'supermarket_id', 'supermarket_name', 'line_number', 'raw_description',
              'quantity', 'unit_price_pence', 'original_pence', 'discount_pence', 'net_pence',
              'item_id', 'item_name', 'brand_id', 'brand_name', 'category_id',
              'category_name', 'pack_size', 'pack_unit'])

    monthly = receipts.groupby(['month', 'currency'], as_index=False).agg(
        receipt_count=('receipt_id', 'size'), total_pence=('total_pence', 'sum'),
    ).sort_values(['month', 'currency'])
    category = items.groupby(['month', 'currency', 'category_id', 'category_name'], dropna=False, as_index=False).agg(
        total_pence=('net_pence', 'sum'), item_count=('receipt_item_id', 'size'),
    ).sort_values(['month', 'currency', 'category_name'])
    supermarket = receipts.groupby(['month', 'currency', 'supermarket_id', 'supermarket_name'], as_index=False).agg(
        receipt_count=('receipt_id', 'size'), total_pence=('total_pence', 'sum'),
    ).sort_values(['month', 'currency', 'supermarket_name'])

    frames = {
        'receipts': receipts, 'receipt_items': items, 'monthly_spending': monthly,
        'category_spending': category, 'supermarket_spending': supermarket,
    }
    paths = {name: output_dir / f'{name}.csv' for name in EXPORTS}
    for name, frame in frames.items():
        frame.to_csv(paths[name], index=False)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=DEFAULT_DATABASE)
    parser.add_argument('--output', type=Path, default=Path('data/analytics'))
    args = parser.parse_args()
    paths = export_verified_data(args.database, args.output)
    print(f'Exported {len(paths)} tables to {args.output.resolve()}')


if __name__ == '__main__':
    main()

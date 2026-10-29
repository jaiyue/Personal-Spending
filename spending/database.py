"""Grocery SQLite connections and schema initialisation."""

import argparse
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = ROOT / "data" / "spending.db"
SCHEMA = ROOT / "sql" / "schema.sql"
DEFAULT_ITEMS = ROOT / "sql" / "default_items.sql"
ACTIVE_TABLES = frozenset({
    "Supermarket", "Brand", "BrandAlias", "categories", "Item", "Receipt", "ReceiptItem", "ocr_runs",
    "correction_audit", "price_observations", "quality_notes", "shopping_lists",
    "shopping_list_items", "budgets",
})


def connect(path=DEFAULT_DATABASE):
    """Return a connection; callers must close it after use.

    Use ``with connection:`` to commit or roll back application transactions.
    Foreign keys must be enabled separately on every SQLite connection.
    """
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def initialize(path=DEFAULT_DATABASE):
    """Create an empty database from the canonical schema when needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(path)
    try:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if not tables:
            connection.executescript(
                "BEGIN IMMEDIATE;\n"
                + SCHEMA.read_text(encoding="utf-8")
                + "\n"
                + DEFAULT_ITEMS.read_text(encoding="utf-8")
            )
            connection.commit()
            return None
        if not ACTIVE_TABLES <= tables:
            raise RuntimeError("Existing database does not match the supported canonical schema.")
        return None
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _sql_literal(value):
    if value is None:
        return 'NULL'
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return str(value)


def export_default_items(database_path=DEFAULT_DATABASE, output_path=DEFAULT_ITEMS):
    """Write the current Item catalogue as seed SQL for future empty databases."""
    with connect(database_path) as connection:
        items = connection.execute('''
            SELECT i.name, b.name AS brand_name, c.name AS category_name,
                   i.barcode, i.pack_size, i.pack_unit
            FROM Item i
            LEFT JOIN Brand b ON b.id=i.brand_id
            LEFT JOIN categories c ON c.id=i.category_id
            ORDER BY i.id
        ''').fetchall()
    brands = sorted({item['brand_name'] for item in items if item['brand_name']})
    lines = [
        '-- Default Item catalogue generated from a reviewed local database.',
        '-- Run: python -m spending.database --export-default-items',
        '',
    ]
    if brands:
        lines.append('INSERT OR IGNORE INTO Brand(name) VALUES')
        lines.append(',\n'.join(f"  ({_sql_literal(brand)})" for brand in brands) + ';')
        lines.append('')
    for item in items:
        brand_id = "(SELECT id FROM Brand WHERE name=" + _sql_literal(item['brand_name']) + ')' if item['brand_name'] else 'NULL'
        category_id = "(SELECT id FROM categories WHERE name=" + _sql_literal(item['category_name']) + ')' if item['category_name'] else 'NULL'
        lines.append(
            'INSERT INTO Item(name, brand_id, category_id, barcode, pack_size, pack_unit) VALUES ('
            + ', '.join((_sql_literal(item['name']), brand_id, category_id,
                         _sql_literal(item['barcode']), _sql_literal(item['pack_size']),
                         _sql_literal(item['pack_unit']))) + ');'
        )
    Path(output_path).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return len(items)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--export-default-items", action='store_true',
                        help='write the current Item catalogue to sql/default_items.sql')
    parser.add_argument("--output", type=Path, default=DEFAULT_ITEMS,
                        help='destination used with --export-default-items')
    args = parser.parse_args()
    if args.export_default_items:
        count = export_default_items(args.path, args.output)
        print(f"Exported {count} default items: {args.output.resolve()}")
        return
    initialize(args.path)
    print(f"Database ready: {args.path.resolve()}")


if __name__ == "__main__":
    main()

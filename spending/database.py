"""Create and connect to the local SQLite database from the split SQL files."""

import argparse
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = ROOT / "data" / "spending.db"
SQL_ROOT = ROOT / "sql"

SCHEMA_FILES = (
    SQL_ROOT / "schema" / "001_reference_tables.sql",
    SQL_ROOT / "schema" / "002_transaction_tables.sql",
)
SEED_FILES = (
    SQL_ROOT / "seed" / "001_brands.sql",
    SQL_ROOT / "seed" / "002_categories.sql",
    SQL_ROOT / "seed" / "003_expense_categories.sql",
)
DATABASE_FILES = (
    *SCHEMA_FILES,
    *SEED_FILES,
    SQL_ROOT / "schema" / "003_indexes.sql",
    SQL_ROOT / "views" / "001_analytics_views.sql",
)
ACTIVE_TABLES = frozenset({
    "Supermarket", "Brand", "BrandAlias", "categories", "ExpenseCategory",
    "MerchantExpenseCategory", "Item", "Receipt", "ReceiptItem", "ocr_runs",
    "correction_audit", "price_observations", "quality_notes", "shopping_lists",
    "shopping_list_items", "budgets",
    "PromotionGroup", "ReceiptItemPromotionGroup", "ItemDiscount",
})


def connect(path=DEFAULT_DATABASE):
    """Return a configured SQLite connection; the caller must close it."""
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def _read_sql(files: tuple[Path, ...]) -> str:
    missing = [str(path.relative_to(ROOT)) for path in files if not path.is_file()]
    if missing:
        raise RuntimeError(f"Database SQL file not found: {', '.join(missing)}")
    return "\n\n".join(path.read_text(encoding="utf-8") for path in files)


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def initialize(path=DEFAULT_DATABASE):
    """Create a database or safely refresh seed data in an existing database."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(path)
    try:
        tables = _tables(connection)
        if not tables:
            connection.executescript("BEGIN IMMEDIATE;\n" + _read_sql(DATABASE_FILES) + "\nCOMMIT;")
            return None

        if not ACTIVE_TABLES <= tables:
            raise RuntimeError("Existing database does not match the supported canonical schema.")

        # Seed scripts use INSERT OR IGNORE, so new reference values can be added
        # without changing receipts or other user data.
        connection.executescript("BEGIN IMMEDIATE;\n" + _read_sql(SEED_FILES) + "\nCOMMIT;")
        return None
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    initialize(args.path)
    print(f"Database ready: {args.path.resolve()}")


if __name__ == "__main__":
    main()

"""Grocery SQLite connections and schema initialisation."""

import argparse
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = ROOT / "data" / "spending.db"
SCHEMA = ROOT / "sql" / "schema.sql"
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
            connection.executescript("BEGIN IMMEDIATE;\n" + SCHEMA.read_text(encoding="utf-8"))
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    initialize(args.path)
    print(f"Database ready: {args.path.resolve()}")


if __name__ == "__main__":
    main()

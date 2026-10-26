"""Grocery SQLite connections and transactional, repeatable schema initialisation."""

import argparse
import hashlib
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = ROOT / "data" / "spending.db"
SCHEMA = ROOT / "sql" / "schema.sql"
ACTIVE_TABLES = frozenset({
    "Supermarket", "categories", "Item", "Receipt", "ReceiptItem", "ocr_runs",
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
    """Create a database from the canonical schema or register its schema version."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(path)
    try:
        has_migrations = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        applied = dict(connection.execute(
            "SELECT version, checksum FROM schema_migrations"
        )) if has_migrations else {}
        schema_sql = SCHEMA.read_text(encoding="utf-8")
        schema_checksum = hashlib.sha256(schema_sql.encode()).hexdigest()
        if SCHEMA.name in applied:
            if applied[SCHEMA.name] != schema_checksum:
                raise RuntimeError(f"Applied migration changed: {SCHEMA.name}")
            return None

        has_tables = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table'"
        ).fetchone()
        if not has_tables:
            connection.executescript("\n".join(("BEGIN IMMEDIATE;", """
                CREATE TABLE schema_migrations (
                    version TEXT PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
            """, schema_sql, f"""
                INSERT INTO schema_migrations(version, checksum)
                VALUES ('{SCHEMA.name}', '{schema_checksum}');
            """)))
            connection.commit()
            return None

        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name <> 'schema_migrations'"
            )
        }
        if not ACTIVE_TABLES <= tables:
            raise RuntimeError("Existing database does not match the supported canonical schema.")
        connection.execute("DELETE FROM schema_migrations")
        connection.execute(
            "INSERT INTO schema_migrations(version, checksum) VALUES (?, ?)",
            (SCHEMA.name, schema_checksum),
        )
        connection.commit()
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

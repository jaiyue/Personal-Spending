"""Grocery SQLite connections and transactional, repeatable schema initialisation."""

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = ROOT / "data" / "spending.db"
SCHEMA = ROOT / "sql" / "schema.sql"
MIGRATIONS = ROOT / "sql" / "migrations"
ACTIVE_TABLES = frozenset({
    "Supermarket", "categories", "Item", "Receipt", "ReceiptItem", "ocr_runs",
    "correction_audit", "price_observations", "quality_notes", "shopping_lists",
    "shopping_list_items", "budgets",
})


def _backfill_vouchers(connection):
    """Split historical OCR vouchers from receipt-level discounts once."""
    from spending.receipt_parser import parse_receipt

    rows = connection.execute('''
        SELECT r.id, r.discount_pence, o.raw_output
        FROM Receipt r JOIN ocr_runs o ON o.id = (
            SELECT id FROM ocr_runs WHERE receipt_id=r.id AND status='succeeded'
            ORDER BY id DESC LIMIT 1
        ) WHERE r.voucher_pence=0 AND o.raw_output IS NOT NULL
    ''')
    for row in rows:
        try:
            voucher = parse_receipt(json.loads(row['raw_output']).get('text', '')).receipt_discount_pence
        except (json.JSONDecodeError, TypeError):
            continue
        if voucher and row['discount_pence'] >= voucher:
            connection.execute(
                'UPDATE Receipt SET discount_pence=?, voucher_pence=? WHERE id=?',
                (row['discount_pence'] - voucher, voucher, row['id']),
            )


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
                for migration in sorted(MIGRATIONS.glob('[0-9]*.sql')):
                    if migration.name in applied:
                        continue
                    sql = migration.read_text(encoding='utf-8')
                    connection.executescript(sql)
                    connection.execute(
                        'INSERT INTO schema_migrations(version, checksum) VALUES (?, ?)',
                        (migration.name, hashlib.sha256(sql.encode()).hexdigest()),
                    )
                connection.execute(
                    'UPDATE schema_migrations SET checksum=? WHERE version=?',
                    (schema_checksum, SCHEMA.name),
                )
                connection.commit()
            _backfill_vouchers(connection)
            connection.commit()
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
            _backfill_vouchers(connection)
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
        _backfill_vouchers(connection)
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

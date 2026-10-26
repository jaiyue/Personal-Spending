"""Grocery SQLite connections and transactional, repeatable schema initialisation."""

import argparse
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = ROOT / "data" / "spending.db"
MIGRATIONS = ROOT / "sql" / "migrations"
SCHEMA = ROOT / "sql" / "schema.sql"


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
    """Create new databases from the canonical schema and upgrade older ones.

    Original table names are reused by the current schema. Legacy layouts
    are archived under legacy_* names without reinterpreting their data.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(path)
    backup = None
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

        pending = []
        for migration in sorted(MIGRATIONS.glob('[0-9]*.sql')):
            sql = migration.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            if migration.name in applied:
                if applied[migration.name] != checksum:
                    raise RuntimeError(f"Applied migration changed: {migration.name}")
            else:
                pending.append((migration.name, checksum, sql))
        if not pending:
            return None
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup = path.with_name(f"{path.name}.{stamp}.bak")
            with closing(sqlite3.connect(backup)) as destination:
                connection.backup(destination)
        # executescript owns its transaction; migration metadata and DDL must
        # commit together, including on the first installation.
        statements = ["BEGIN IMMEDIATE;", """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );
        """]
        for name, checksum, sql in pending:
            if name == '002_original_table_names.sql':
                # The original layout can coexist with migration 001. Archive
                # only recognised old tables before reusing their exact names.
                for table, primary_key in (
                    ('Supermarket', 'SupermarketID'), ('Item', 'ItemID'),
                    ('Receipt', 'ReceiptID'), ('ReceiptItem', 'ReceiptItemID'),
                ):
                    columns = {row['name'] for row in connection.execute(
                        f'PRAGMA table_info("{table}")'
                    )}
                    if columns:
                        if primary_key not in columns:
                            raise RuntimeError(f'Unrecognised original table layout: {table}')
                        statements.append(f'ALTER TABLE "{table}" RENAME TO "legacy_{table}";')
            statements.append(sql)
            escaped_name = name.replace("'", "''")
            statements.append(
                f"INSERT INTO schema_migrations(version, checksum) "
                f"VALUES ('{escaped_name}', '{checksum}');"
            )
        connection.executescript("\n".join(statements))
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Database contains invalid foreign key references")
        connection.commit()
        return backup
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    backup = initialize(args.path)
    print(f"Database ready: {args.path.resolve()}")
    if backup:
        print(f"Previous database backup: {backup.resolve()}")


if __name__ == "__main__":
    main()

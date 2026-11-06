# Database SQL

The database is split by purpose and dependency. Run the Python initializer
from the repository root instead of executing individual SQL files:

```bash
python -m spending.database
```

Use another database path when needed:

```bash
python -m spending.database --path /tmp/personal-spending.db
```

For a new database, the initializer runs these files in order:

1. `schema/001_reference_tables.sql`
2. `schema/002_transaction_tables.sql`
3. `seed/001_brands.sql`
4. `seed/002_categories.sql`
5. `seed/003_expense_categories.sql`
6. `schema/003_indexes.sql`
7. `views/001_analytics_views.sql`

When the database already has the complete schema, initialization only reruns
the `seed` files. Their `INSERT OR IGNORE` statements add new reference values
without replacing receipts or other existing data. Structural changes during
development still require rebuilding the database.

Every application connection enables `PRAGMA foreign_keys = ON` through
`spending.database.connect`.

# Database SQL

`schema.sql` is the complete, canonical SQLite schema for a new database. It
creates the active grocery tables, indexes and analytical views in one run.

`migrations/` contains the immutable historical upgrade scripts for databases
created before the schema was consolidated. They are only used when an existing
database has recorded their checksums in `schema_migrations`.

Use `python -m spending.database` to initialise a database. Do not run an
individual file against an existing database: the initializer selects the safe
creation or upgrade path and creates a backup before an upgrade.

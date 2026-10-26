# Database SQL

`schema.sql` is the complete, canonical SQLite schema for a new database. It
creates the active grocery tables, indexes and analytical views in one run.

Use `python -m spending.database` to initialise a database. Do not run an
individual file against an existing database: the initializer selects the safe
creation path.

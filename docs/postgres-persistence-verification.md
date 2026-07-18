# PostgreSQL Persistence Verification

SQLite remains the default unit-test path. Run this check separately when changing persistence SQL, migrations,
constraints, indexes, transaction boundaries, or PostGIS values.

The check is destructive to the database named by `POSTGRES_TEST_DATABASE_URL`. It refuses to run unless that
database name ends in `_test` or `_verification`. Never point it at a development, staging, or production database.

Create a dedicated local database and run the check:

```bash
docker compose up -d postgis
docker compose exec postgis dropdb --if-exists -U postgres consorcio_fenix_test
docker compose exec postgis createdb -U postgres consorcio_fenix_test
POSTGRES_TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/consorcio_fenix_test \
  uv run pytest -q tests/test_postgres_persistence.py
```

The test applies all Alembic migrations, verifies cold ingestion, an identical unchanged rerun, a changed map
subset, normalized Route Version history, child-row de-duplication, durable Scrape Run completion, and the named
PostgreSQL constraints and B-tree/GiST indexes used by advisory reads.

The normal SQLite suite covers changed source/map/fare subsets plus injected first, middle, and final batch
failures, active-batch rollback, durable failed status, and retry reuse:

```bash
uv run pytest -q tests/test_batch_persistence.py tests/test_persistence.py tests/test_cli.py
```

No performance thresholds or benchmark acceptance gates are part of either command. Logs are written to stderr so
CLI stdout remains the stable, concise count summary. Inspect these structured events:

- `fetch_complete`: fetched Route count, duration, and Routes per second.
- `persistence_batch_complete`: committed batch number, Route count, proposed-row count, duration, and rows per
  second.
- `persistence_batch_failed`: the same batch context for the active transaction that rolled back.
- `persistence_complete`: successful Scrape Run totals, duration, and rows per second.

Database writes use one sequential writer. A failed data batch is rolled back independently, and failed Scrape Run
finalization is retried in a fresh control transaction before the original persistence error is returned.

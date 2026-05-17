# Consórcio Fênix Scraper

Python 3.12 batch CLI for scraping Consórcio Fênix route pages, schedules, textual itineraries, and KML route shapes into PostGIS.

## Local Setup

```bash
uv sync
docker compose up -d postgis
uv run alembic upgrade head
```

The same workflow is available through `make`:

```bash
make sync
make db-up
make migrate
```

Run a dry fixture parse:

```bash
uv run consorcio-fenix scrape-routes --dry-run \
  --route-html tests/fixtures/route_page.html \
  --map-html tests/fixtures/map_page.html
```

Or:

```bash
make dry-run
```

Set `LOG_LEVEL=DEBUG` for more detailed scraper diagnostics:

```bash
LOG_LEVEL=DEBUG make dry-run
```

Run a limited live scrape:

```bash
uv run consorcio-fenix scrape-routes --limit 3
```

Live route pages and map pages are fetched concurrently. The default is 4 concurrent routes:

```bash
uv run consorcio-fenix scrape-routes --limit 10 --concurrency 4
CONSORCIO_FENIX_HTTP_CONCURRENCY=4 uv run consorcio-fenix scrape-routes --limit 10
```

Or:

```bash
make scrape LIMIT=3
```

The default `DATABASE_URL` points at the PostGIS service from `docker-compose.yml`.
Override it with `DATABASE_URL=...` when targeting another database.
You can also create a local `.env` file:

```env
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE
```

Environment variables still take precedence over values from `.env`.

## Scope

Consórcio Fênix pages are treated as canonical for route metadata, schedules, textual itineraries, and KML shapes. Stop coordinate enrichment is isolated behind a Floripa no Ponto adapter boundary and currently reports unavailable instead of failing route ingestion.

## Read Contracts

- [Candidate Route Direction Read Contract](docs/candidate-route-direction-read-contract.md)

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

Or:

```bash
make scrape LIMIT=3
```

The default `DATABASE_URL` points at the PostGIS service from `docker-compose.yml`.
Override it with `DATABASE_URL=...` when targeting another database.

## Scope

Consórcio Fênix pages are treated as canonical for route metadata, schedules, textual itineraries, and KML shapes. Stop coordinate enrichment is isolated behind a Floripa no Ponto adapter boundary and currently reports unavailable instead of failing route ingestion.

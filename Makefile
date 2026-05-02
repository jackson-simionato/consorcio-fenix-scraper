DATABASE_URL ?= postgresql+psycopg://postgres:postgres@localhost:5432/consorcio_fenix
LIMIT ?= 3

.PHONY: help sync db-up db-down db-logs migrate migrate-sql revision test compile dry-run scrape

help:
	@printf "Available targets:\n"
	@printf "  make sync         Install/update Python dependencies with uv\n"
	@printf "  make db-up        Start local PostGIS with Docker Compose\n"
	@printf "  make db-down      Stop local PostGIS\n"
	@printf "  make db-logs      Follow PostGIS logs\n"
	@printf "  make migrate      Run Alembic migrations against DATABASE_URL\n"
	@printf "  make migrate-sql  Render Alembic migration SQL without applying it\n"
	@printf "  make revision     Create an Alembic revision: make revision MSG=\"message\"\n"
	@printf "  make test         Run the test suite\n"
	@printf "  make compile      Compile src and tests\n"
	@printf "  make dry-run      Parse bundled fixture pages without database writes\n"
	@printf "                    Use LOG_LEVEL=DEBUG make dry-run for verbose logs\n"
	@printf "  make scrape       Run a limited live scrape: make scrape LIMIT=3\n"

sync:
	uv sync

db-up:
	docker compose up -d postgis

db-down:
	docker compose down

db-logs:
	docker compose logs -f postgis

migrate:
	DATABASE_URL="$(DATABASE_URL)" uv run alembic upgrade head

migrate-sql:
	DATABASE_URL="$(DATABASE_URL)" uv run alembic upgrade head --sql

revision:
	@if [ -z "$(MSG)" ]; then echo 'Usage: make revision MSG="message"'; exit 1; fi
	uv run alembic revision --autogenerate -m "$(MSG)"

test:
	uv run pytest -q

compile:
	uv run python -m compileall src tests

dry-run:
	uv run consorcio-fenix scrape-routes --dry-run \
		--route-html tests/fixtures/route_page.html \
		--map-html tests/fixtures/map_page.html

scrape:
	DATABASE_URL="$(DATABASE_URL)" uv run consorcio-fenix scrape-routes --limit "$(LIMIT)"

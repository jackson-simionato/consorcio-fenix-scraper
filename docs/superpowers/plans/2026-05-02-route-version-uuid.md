# Route Version UUID Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store database entity identities as UUIDs and prevent duplicate route version history rows for unchanged `source_hash` plus `map_hash` snapshots.

**Architecture:** Keep the current compact SQLAlchemy persistence module, but change its ID columns and helpers to UUID-aware types. Add a null-safe route version lookup before insertion, backed by a PostgreSQL `NULLS NOT DISTINCT` uniqueness constraint in the initial Alembic schema.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, PostgreSQL/PostGIS, pytest, Pydantic 2.

---

## File Map

- `src/consorcio_fenix_scraper/db.py`: UUID SQLAlchemy model IDs, null-safe route version lookup, duplicate-version reuse behavior.
- `src/consorcio_fenix_scraper/domain.py`: UUID type for persisted domain IDs.
- `migrations/versions/20260502_0001_initial_postgis_schema.py`: UUID schema and route version uniqueness constraint.
- `tests/test_persistence.py`: focused persistence tests for UUID IDs and route version de-duplication.

## Task 1: Add Persistence Tests for Version De-Duplication

**Files:**
- Modify: `tests/test_persistence.py`

- [ ] **Step 1: Write the failing tests**

Add these imports and helpers to `tests/test_persistence.py`:

```python
from datetime import date
from uuid import UUID

from sqlalchemy import create_mock_engine
from sqlalchemy.orm import Session

from consorcio_fenix_scraper.db import (
    Base,
    RouteVersionRecord,
    _persist_snapshot,
    _uuid_pk,
)
from consorcio_fenix_scraper.domain import ParsedRoutePage, RouteSnapshot
```

Add these test helpers:

```python
def _snapshot(source_hash: str = "source-a", map_hash: str | None = "map-a") -> RouteSnapshot:
    return RouteSnapshot(
        route=ParsedRoutePage(
            code="110",
            name="TICEN - TITRI",
            slug="ticen-titri",
            page_url="https://www.consorciofenix.com.br/horarios/ticen-titri,110",
            map_url="https://www.consorciofenix.com.br/mapa/110",
            category="convencional",
            fare_cents=600,
            last_changed=date(2026, 5, 2),
        ),
        source_hash=source_hash,
        map_hash=map_hash,
    )
```

Add these tests:

```python
def test_uuid_pk_generates_uuid_values():
    column = _uuid_pk()

    generated = column.default.arg()

    assert isinstance(generated, UUID)


def test_reuses_existing_route_version_when_source_and_map_hash_match(db_session: Session):
    first = _persist_snapshot(db_session, _uuid_pk().default.arg(), _snapshot())
    second = _persist_snapshot(db_session, _uuid_pk().default.arg(), _snapshot())

    versions = db_session.query(RouteVersionRecord).all()

    assert second.id == first.id
    assert len(versions) == 1
    assert versions[0].is_current is True


def test_creates_new_route_version_when_source_hash_changes(db_session: Session):
    first = _persist_snapshot(db_session, _uuid_pk().default.arg(), _snapshot(source_hash="source-a"))
    second = _persist_snapshot(db_session, _uuid_pk().default.arg(), _snapshot(source_hash="source-b"))

    versions = db_session.query(RouteVersionRecord).order_by(RouteVersionRecord.created_at).all()

    assert first.id != second.id
    assert len(versions) == 2
    assert versions[-1].is_current is True


def test_creates_new_route_version_when_map_hash_changes(db_session: Session):
    first = _persist_snapshot(db_session, _uuid_pk().default.arg(), _snapshot(map_hash="map-a"))
    second = _persist_snapshot(db_session, _uuid_pk().default.arg(), _snapshot(map_hash="map-b"))

    versions = db_session.query(RouteVersionRecord).order_by(RouteVersionRecord.created_at).all()

    assert first.id != second.id
    assert len(versions) == 2
    assert versions[-1].is_current is True
```

If `db_session` does not exist, add a pytest fixture that builds a temporary PostgreSQL test session using the same `DATABASE_URL` conventions already used by the project. If a live database is unavailable, skip these DB integration tests with `pytest.skip("DATABASE_URL is required for persistence integration tests")`.

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
uv run pytest tests/test_persistence.py -v
```

Expected: at least the duplicate-version test fails because `_persist_snapshot()` currently inserts a new route version every time, and the UUID test fails because IDs are currently integer columns.

## Task 2: Convert SQLAlchemy Models to UUID IDs

**Files:**
- Modify: `src/consorcio_fenix_scraper/db.py`
- Modify: `src/consorcio_fenix_scraper/domain.py`

- [ ] **Step 1: Update imports and add the UUID column helper**

In `src/consorcio_fenix_scraper/db.py`, add:

```python
from uuid import UUID as PyUUID, uuid4
```

Change the PostgreSQL import to:

```python
from sqlalchemy.dialects.postgresql import JSONB, UUID
```

Add below `class Base`:

```python
def _uuid_pk() -> Mapped[PyUUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
```

- [ ] **Step 2: Change mapped ID fields**

Update primary and foreign key mapped types in `db.py`:

```python
id: Mapped[PyUUID] = _uuid_pk()
route_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("routes.id"), index=True)
scrape_run_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("scrape_runs.id"), index=True)
route_version_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("route_versions.id"), index=True)
```

Keep non-ID integer fields as `Integer`.

- [ ] **Step 3: Update function signatures**

Change:

```python
def _persist_snapshot(session: Session, run_id: PyUUID, snapshot: RouteSnapshot) -> RouteVersionRecord:
def _persist_children(session: Session, route_version_id: PyUUID, snapshot: RouteSnapshot) -> None:
```

In `src/consorcio_fenix_scraper/domain.py`, add:

```python
from uuid import UUID
```

Change:

```python
id: UUID | None = None
```

- [ ] **Step 4: Run UUID-focused test**

Run:

```bash
uv run pytest tests/test_persistence.py::test_uuid_pk_generates_uuid_values -v
```

Expected: PASS.

## Task 3: Add Route Version Reuse Behavior

**Files:**
- Modify: `src/consorcio_fenix_scraper/db.py`
- Test: `tests/test_persistence.py`

- [ ] **Step 1: Add null-safe existing-version lookup**

In `_persist_snapshot()`, after route metadata is updated and before creating a new `RouteVersionRecord`, add:

```python
existing_version = session.scalar(
    select(RouteVersionRecord).where(
        RouteVersionRecord.route_id == route.id,
        RouteVersionRecord.source_hash == snapshot.source_hash,
        RouteVersionRecord.map_hash.is_not_distinct_from(snapshot.map_hash),
    )
)
session.query(RouteVersionRecord).filter(RouteVersionRecord.route_id == route.id).update({"is_current": False})
if existing_version is not None:
    existing_version.is_current = True
    session.flush()
    return existing_version
```

Leave the new-version insertion after this block.

- [ ] **Step 2: Keep child insertion only for new versions**

In `persist_snapshots()`, capture whether a version already existed before inserting children. Use a helper return value or an existence check that avoids adding duplicate children. The simplest implementation is to make `_persist_snapshot()` return a tuple:

```python
def _persist_snapshot(session: Session, run_id: PyUUID, snapshot: RouteSnapshot) -> tuple[RouteVersionRecord, bool]:
```

Return `(existing_version, False)` when reusing and `(version, True)` when inserting. Then update the caller:

```python
version, created = _persist_snapshot(session, run.id, snapshot)
if created:
    _persist_children(session, version.id, snapshot)
```

Update tests to unpack the tuple where they call `_persist_snapshot()` directly.

- [ ] **Step 3: Run de-dup tests**

Run:

```bash
uv run pytest tests/test_persistence.py -v
```

Expected: duplicate same-hash test passes, changed `source_hash` and changed `map_hash` tests pass.

## Task 4: Update Alembic Initial Schema

**Files:**
- Modify: `migrations/versions/20260502_0001_initial_postgis_schema.py`

- [ ] **Step 1: Add UUID import**

Use:

```python
from sqlalchemy.dialects import postgresql
```

The file already imports this namespace. Use `postgresql.UUID(as_uuid=True)` for ID columns.

- [ ] **Step 2: Change ID and FK columns**

For every primary key and foreign key ID column, change `sa.Integer()` to:

```python
postgresql.UUID(as_uuid=True)
```

This includes `id`, `route_id`, `scrape_run_id`, and `route_version_id`. Leave `fare_cents`, `sequence`, and other count-like fields as integers.

- [ ] **Step 3: Add route version unique constraint**

Inside the `route_versions` table definition, add:

```python
sa.UniqueConstraint(
    "route_id",
    "source_hash",
    "map_hash",
    name="uq_route_versions_route_source_map_hash",
    postgresql_nulls_not_distinct=True,
),
```

- [ ] **Step 4: Run migration syntax check**

Run:

```bash
uv run python -m py_compile migrations/versions/20260502_0001_initial_postgis_schema.py
```

Expected: command exits with code 0.

## Task 5: Full Verification

**Files:**
- No code changes unless verification exposes a failure.

- [ ] **Step 1: Run persistence tests**

Run:

```bash
uv run pytest tests/test_persistence.py -v
```

Expected: PASS.

- [ ] **Step 2: Run the complete test suite**

Run:

```bash
uv run pytest -v
```

Expected: PASS.

- [ ] **Step 3: Inspect final diff**

Run:

```bash
git diff -- src/consorcio_fenix_scraper/db.py src/consorcio_fenix_scraper/domain.py migrations/versions/20260502_0001_initial_postgis_schema.py tests/test_persistence.py
```

Expected: diff only contains UUID ID changes, route version de-duplication logic, migration updates, and tests.

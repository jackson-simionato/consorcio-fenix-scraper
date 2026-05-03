# Service Directions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store schedule departure groups as service directions and link them to directed KML geometries with explicit confidence metadata.

**Architecture:** Keep parsing, inference, and persistence separate. The route parser extracts schedule groups exactly as the website presents them; a new inference module maps those groups to KML `route_directions`; persistence writes `service_directions` between route versions and schedule entries.

**Tech Stack:** Python 3.12, Pydantic v2, BeautifulSoup, SQLAlchemy 2.0, GeoAlchemy2, Alembic, pytest.

---

## File Map

- Modify `src/consorcio_fenix_scraper/domain.py`: add `ServiceDirection`, `ServiceDirectionMatch`, and match enums; extend `ParsedRoutePage`.
- Modify `src/consorcio_fenix_scraper/parsers/route_page.py`: parse schedule groups explicitly while preserving flattened `route.schedules`.
- Create `src/consorcio_fenix_scraper/directions.py`: infer service-direction-to-KML-direction matches.
- Modify `src/consorcio_fenix_scraper/db.py`: add `ServiceDirectionRecord`, persist inferred links, add `service_direction_id` to schedules.
- Modify `src/consorcio_fenix_scraper/cli.py`: run inference before building `RouteSnapshot`; keep summary counts unchanged.
- Modify `migrations/versions/20260502_0001_initial_postgis_schema.py`: add `service_directions` and schedule FK columns to the initial schema.
- Modify `tests/test_parsers.py`: verify explicit schedule groups.
- Create `tests/test_directions.py`: verify inference behavior.
- Modify `tests/test_persistence.py`: verify service direction rows and schedule FKs.
- Modify `tests/test_cli.py`: verify dry-run still reports schedule and geometry counts.

## Task 1: Domain Models

**Files:**
- Modify: `src/consorcio_fenix_scraper/domain.py`
- Test: `tests/test_parsers.py`

- [ ] **Step 1: Write the failing parser-domain test**

Add this assertion block to `test_route_page_parser_handles_live_schedule_cards_data_src_map_and_itinerary_list` after the existing `route.itinerary_steps` assertion:

```python
    assert [(direction.sequence, direction.departure_label) for direction in route.service_directions] == [
        (1, "Saída Abraão"),
        (2, "Saída TICEN - Plataforma B - Box 9"),
    ]
    assert [
        (entry.day_type, entry.departure_label, entry.time, entry.flags)
        for entry in route.service_directions[0].schedules
    ] == [
        ("Dias Úteis", "Saída Abraão", "05:30", ("E", "M")),
    ]
    assert [
        (entry.day_type, entry.departure_label, entry.time, entry.flags)
        for entry in route.service_directions[1].schedules
    ] == [
        ("Sábado", "Saída TICEN - Plataforma B - Box 9", "00:15", ("E", "R")),
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_parsers.py::test_route_page_parser_handles_live_schedule_cards_data_src_map_and_itinerary_list -v`

Expected: FAIL with an attribute error for `service_directions`.

- [ ] **Step 3: Add domain types**

In `src/consorcio_fenix_scraper/domain.py`, add these enums and models after `ScheduleEntry`:

```python
class DirectionMatchConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class DirectionMatchMethod(StrEnum):
    LABEL_ENDPOINT = "label_endpoint"
    LABEL_ORDER_IDA_VOLTA = "label_order_ida_volta"
    SEQUENCE_IDA_VOLTA = "sequence_ida_volta"
    UNMATCHED = "unmatched"


class ServiceDirection(BaseModel):
    sequence: int
    departure_label: str
    normalized_name: str | None = None
    direction_kind: str | None = None
    schedules: list[ScheduleEntry] = Field(default_factory=list)


class ServiceDirectionMatch(BaseModel):
    service_direction_sequence: int
    route_direction_sequence: int | None = None
    confidence: DirectionMatchConfidence = DirectionMatchConfidence.NONE
    method: DirectionMatchMethod = DirectionMatchMethod.UNMATCHED
    notes: dict[str, str] = Field(default_factory=dict)
```

Then update `ParsedRoutePage`:

```python
class ParsedRoutePage(BaseModel):
    code: str
    name: str
    slug: str
    page_url: str
    map_url: str | None = None
    category: str | None = None
    fare_cents: int | None = None
    last_changed: date | None = None
    service_directions: list[ServiceDirection] = Field(default_factory=list)
    schedules: list[ScheduleEntry] = Field(default_factory=list)
    itinerary_steps: list[ItineraryStep] = Field(default_factory=list)
```

Update `RouteSnapshot`:

```python
class RouteSnapshot(BaseModel):
    route: ParsedRoutePage
    directions: list[RouteDirection] = Field(default_factory=list)
    direction_matches: list[ServiceDirectionMatch] = Field(default_factory=list)
    source_hash: str
    map_hash: str | None = None
```

- [ ] **Step 4: Run test to verify the domain error is gone and parser grouping still fails**

Run: `uv run pytest tests/test_parsers.py::test_route_page_parser_handles_live_schedule_cards_data_src_map_and_itinerary_list -v`

Expected: FAIL because `route.service_directions` is empty.

- [ ] **Step 5: Commit**

```bash
git add src/consorcio_fenix_scraper/domain.py tests/test_parsers.py
git commit -m "test: expect parsed service directions"
```

## Task 2: Route Page Parser Service Groups

**Files:**
- Modify: `src/consorcio_fenix_scraper/parsers/route_page.py`
- Test: `tests/test_parsers.py`

- [ ] **Step 1: Update imports**

Change the domain import in `route_page.py` to:

```python
from consorcio_fenix_scraper.domain import ItineraryStep, ParsedRoutePage, ScheduleEntry, ServiceDirection
```

- [ ] **Step 2: Refactor `parse_route_page` to build grouped and flattened schedules**

Replace the `return ParsedRoutePage(...)` body setup with:

```python
    service_directions = _parse_service_directions(soup)
    schedules = [entry for direction in service_directions for entry in direction.schedules]

    return ParsedRoutePage(
        code=code,
        name=name,
        slug=slug,
        page_url=page_url,
        map_url=map_url,
        category=_find_labeled_value(soup, "Categoria"),
        fare_cents=_parse_fare(_find_labeled_value(soup, "Tarifa")),
        last_changed=_parse_brazilian_date(_find_labeled_value(soup, "Última alteração")),
        service_directions=service_directions,
        schedules=schedules,
        itinerary_steps=_parse_itinerary(soup),
    )
```

- [ ] **Step 3: Add service-direction parsing helpers**

Replace `_parse_schedules` and `_parse_schedule_cards` with these functions:

```python
def _parse_service_directions(soup: BeautifulSoup) -> list[ServiceDirection]:
    card_directions = _parse_schedule_card_groups(soup)
    if card_directions:
        return card_directions
    return _parse_table_schedule_groups(soup)


def _parse_schedule_card_groups(soup: BeautifulSoup) -> list[ServiceDirection]:
    directions: list[ServiceDirection] = []
    for sequence, tab in enumerate(soup.find_all(class_=re.compile(r"\bmy-subtab-content\b")), start=1):
        if not isinstance(tab, Tag):
            continue
        heading = tab.find(re.compile("^h[1-6]$"))
        label = _text(heading)
        if not label:
            continue
        schedules = _parse_schedule_cards_in_group(tab, label)
        if schedules:
            directions.append(ServiceDirection(sequence=sequence, departure_label=label, schedules=schedules))
    return directions


def _parse_schedule_cards_in_group(group: Tag, label: str) -> list[ScheduleEntry]:
    schedules: list[ScheduleEntry] = []
    for node in group.find_all(attrs={"data-semana": True, "data-horario": True}):
        if not isinstance(node, Tag):
            continue
        day_type = str(node["data-semana"]).strip()
        time = str(node["data-horario"]).strip()
        if not day_type or not TIME_RE.fullmatch(time):
            continue
        schedules.append(
            ScheduleEntry(
                day_type=day_type,
                departure_label=label,
                time=time.zfill(5),
                flags=tuple(FLAG_RE.findall(_text(node))),
            )
        )
    return schedules


def _parse_table_schedule_groups(soup: BeautifulSoup) -> list[ServiceDirection]:
    grouped: dict[str, list[ScheduleEntry]] = {}
    order: list[str] = []
    root = soup.find(id=re.compile("horario", re.IGNORECASE)) or soup
    for table in root.find_all("table"):
        day_type = _table_day_type(table)
        if not day_type:
            continue
        headers = [_text(cell) for cell in table.find_all("th")]
        if not headers:
            continue
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            for index, cell in enumerate(cells):
                label = headers[index] if index < len(headers) else headers[-1]
                if label not in grouped:
                    grouped[label] = []
                    order.append(label)
                grouped[label].extend(_parse_schedule_cell(day_type, label, _text(cell)))
    return [
        ServiceDirection(sequence=index, departure_label=label, schedules=grouped[label])
        for index, label in enumerate(order, start=1)
        if grouped[label]
    ]
```

Remove `_schedule_card_label`; it is no longer used.

- [ ] **Step 4: Run parser tests**

Run: `uv run pytest tests/test_parsers.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/consorcio_fenix_scraper/parsers/route_page.py tests/test_parsers.py
git commit -m "feat: parse schedule service directions"
```

## Task 3: Direction Inference Module

**Files:**
- Create: `src/consorcio_fenix_scraper/directions.py`
- Create: `tests/test_directions.py`

- [ ] **Step 1: Write failing inference tests**

Create `tests/test_directions.py`:

```python
from consorcio_fenix_scraper.directions import infer_service_direction_matches
from consorcio_fenix_scraper.domain import (
    DirectionMatchConfidence,
    DirectionMatchMethod,
    RouteDirection,
    ScheduleEntry,
    ServiceDirection,
)


def _service(sequence: int, label: str) -> ServiceDirection:
    return ServiceDirection(
        sequence=sequence,
        departure_label=label,
        schedules=[ScheduleEntry(day_type="Sábado", departure_label=label, time="06:00")],
    )


def test_infers_terminal_volta_and_neighborhood_ida_with_medium_confidence():
    services = [
        _service(1, "Saída Bairro de Fátima"),
        _service(2, "Saída TICEN - Plataforma B - Box 6"),
    ]
    directions = [
        RouteDirection(name="VOLTA", coordinates=[(-48.55, -27.59), (-48.59, -27.58)]),
        RouteDirection(name="IDA", coordinates=[(-48.59, -27.58), (-48.55, -27.59)]),
    ]

    matches = infer_service_direction_matches(services, directions)

    assert [(match.service_direction_sequence, match.route_direction_sequence) for match in matches] == [
        (1, 2),
        (2, 1),
    ]
    assert [match.confidence for match in matches] == [
        DirectionMatchConfidence.MEDIUM,
        DirectionMatchConfidence.MEDIUM,
    ]
    assert [match.method for match in matches] == [
        DirectionMatchMethod.LABEL_ORDER_IDA_VOLTA,
        DirectionMatchMethod.LABEL_ORDER_IDA_VOLTA,
    ]


def test_uses_low_confidence_sequence_match_when_labels_do_not_identify_terminal_side():
    services = [_service(1, "Saída Ponto A"), _service(2, "Saída Ponto B")]
    directions = [
        RouteDirection(name="VOLTA", coordinates=[(-48.55, -27.59), (-48.59, -27.58)]),
        RouteDirection(name="IDA", coordinates=[(-48.59, -27.58), (-48.55, -27.59)]),
    ]

    matches = infer_service_direction_matches(services, directions)

    assert [(match.service_direction_sequence, match.route_direction_sequence) for match in matches] == [
        (1, 2),
        (2, 1),
    ]
    assert [match.confidence for match in matches] == [
        DirectionMatchConfidence.LOW,
        DirectionMatchConfidence.LOW,
    ]
    assert [match.method for match in matches] == [
        DirectionMatchMethod.SEQUENCE_IDA_VOLTA,
        DirectionMatchMethod.SEQUENCE_IDA_VOLTA,
    ]


def test_unmatched_when_ida_volta_pair_is_not_available():
    services = [_service(1, "Saída Bairro"), _service(2, "Saída Terminal")]
    directions = [RouteDirection(name="Circular", coordinates=[(-48.55, -27.59), (-48.59, -27.58)])]

    matches = infer_service_direction_matches(services, directions)

    assert [(match.service_direction_sequence, match.route_direction_sequence) for match in matches] == [
        (1, None),
        (2, None),
    ]
    assert [match.confidence for match in matches] == [
        DirectionMatchConfidence.NONE,
        DirectionMatchConfidence.NONE,
    ]
    assert [match.method for match in matches] == [
        DirectionMatchMethod.UNMATCHED,
        DirectionMatchMethod.UNMATCHED,
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_directions.py -v`

Expected: FAIL with `ModuleNotFoundError` for `consorcio_fenix_scraper.directions`.

- [ ] **Step 3: Implement inference module**

Create `src/consorcio_fenix_scraper/directions.py`:

```python
from __future__ import annotations

import re
import unicodedata

from consorcio_fenix_scraper.domain import (
    DirectionMatchConfidence,
    DirectionMatchMethod,
    RouteDirection,
    ServiceDirection,
    ServiceDirectionMatch,
)

TERMINAL_TOKENS = ("ticen", "titri", "tican", "tirio", "tilag", "tisan", "terminal")


def infer_service_direction_matches(
    service_directions: list[ServiceDirection],
    route_directions: list[RouteDirection],
) -> list[ServiceDirectionMatch]:
    ida_sequence = _find_direction_sequence(route_directions, "ida")
    volta_sequence = _find_direction_sequence(route_directions, "volta")
    if ida_sequence is None or volta_sequence is None:
        return [_unmatched(service.sequence) for service in service_directions]

    services = sorted(service_directions, key=lambda service: service.sequence)
    if len(services) != 2:
        return [_unmatched(service.sequence) for service in services]

    first, second = services
    first_terminal = _looks_like_terminal_departure(first.departure_label)
    second_terminal = _looks_like_terminal_departure(second.departure_label)

    if first_terminal != second_terminal:
        return [
            _matched(
                first.sequence,
                volta_sequence if first_terminal else ida_sequence,
                DirectionMatchConfidence.MEDIUM,
                DirectionMatchMethod.LABEL_ORDER_IDA_VOLTA,
                {"departure_label": first.departure_label},
            ),
            _matched(
                second.sequence,
                volta_sequence if second_terminal else ida_sequence,
                DirectionMatchConfidence.MEDIUM,
                DirectionMatchMethod.LABEL_ORDER_IDA_VOLTA,
                {"departure_label": second.departure_label},
            ),
        ]

    return [
        _matched(
            first.sequence,
            ida_sequence,
            DirectionMatchConfidence.LOW,
            DirectionMatchMethod.SEQUENCE_IDA_VOLTA,
            {"reason": "first schedule group mapped to ida by observed source order"},
        ),
        _matched(
            second.sequence,
            volta_sequence,
            DirectionMatchConfidence.LOW,
            DirectionMatchMethod.SEQUENCE_IDA_VOLTA,
            {"reason": "second schedule group mapped to volta by observed source order"},
        ),
    ]


def _find_direction_sequence(route_directions: list[RouteDirection], kind: str) -> int | None:
    pattern = re.compile(rf"(^|[^a-z]){re.escape(kind)}([^a-z]|$)", re.IGNORECASE)
    for sequence, direction in enumerate(route_directions, start=1):
        if pattern.search(_normalize(direction.name)):
            return sequence
    return None


def _looks_like_terminal_departure(label: str) -> bool:
    normalized = _normalize(label)
    return any(token in normalized for token in TERMINAL_TOKENS)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in decomposed if not unicodedata.combining(char))
    return ascii_value.lower()


def _matched(
    service_sequence: int,
    route_sequence: int,
    confidence: DirectionMatchConfidence,
    method: DirectionMatchMethod,
    notes: dict[str, str],
) -> ServiceDirectionMatch:
    return ServiceDirectionMatch(
        service_direction_sequence=service_sequence,
        route_direction_sequence=route_sequence,
        confidence=confidence,
        method=method,
        notes=notes,
    )


def _unmatched(service_sequence: int) -> ServiceDirectionMatch:
    return ServiceDirectionMatch(service_direction_sequence=service_sequence)
```

- [ ] **Step 4: Run inference tests**

Run: `uv run pytest tests/test_directions.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/consorcio_fenix_scraper/directions.py tests/test_directions.py
git commit -m "feat: infer service direction geometry matches"
```

## Task 4: CLI Snapshot Inference

**Files:**
- Modify: `src/consorcio_fenix_scraper/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Add dry-run assertion for inferred service directions**

In `test_dry_run_cli_emits_lifecycle_logs_without_changing_summary`, add:

```python
    assert "service_directions=2" in caplog.text
    assert "direction_matches=2" in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_dry_run_cli_emits_lifecycle_logs_without_changing_summary -v`

Expected: FAIL because the log does not include service direction counts.

- [ ] **Step 3: Run inference in snapshot creation**

Add this import to `cli.py`:

```python
from consorcio_fenix_scraper.directions import infer_service_direction_matches
```

In `_load_fixture_snapshots`, add:

```python
    direction_matches = infer_service_direction_matches(route.service_directions, directions)
```

Update the debug log arguments and message:

```python
        "Parsed fixture route code=%s schedules=%s service_directions=%s directions=%s direction_matches=%s source_hash=%s map_hash=%s",
        route.code,
        len(route.schedules),
        len(route.service_directions),
        len(directions),
        len(direction_matches),
        source_hash,
        map_hash,
```

Update the returned snapshot:

```python
    return [
        RouteSnapshot(
            route=route,
            directions=directions,
            direction_matches=direction_matches,
            source_hash=source_hash,
            map_hash=map_hash,
        )
    ]
```

In `_fetch_live_snapshots`, add:

```python
            direction_matches = infer_service_direction_matches(route.service_directions, directions)
```

Update the info log:

```python
                "Parsed route %s: schedules=%s service_directions=%s directions=%s direction_matches=%s itinerary_steps=%s",
                route.code,
                len(route.schedules),
                len(route.service_directions),
                len(directions),
                len(direction_matches),
                len(route.itinerary_steps),
```

Update the live `RouteSnapshot` creation to include:

```python
                    direction_matches=direction_matches,
```

- [ ] **Step 4: Run CLI tests**

Run: `uv run pytest tests/test_cli.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/consorcio_fenix_scraper/cli.py tests/test_cli.py
git commit -m "feat: attach direction matches to route snapshots"
```

## Task 5: Persistence Records and Child Inserts

**Files:**
- Modify: `src/consorcio_fenix_scraper/db.py`
- Modify: `tests/test_persistence.py`

- [ ] **Step 1: Expand SQLite test schema setup**

Update imports in `tests/test_persistence.py`:

```python
from consorcio_fenix_scraper.db import (
    Base,
    RouteDirectionRecord,
    RouteRecord,
    RouteVersionRecord,
    ScheduleEntryRecord,
    ScrapeRunRecord,
    ServiceDirectionRecord,
    _linestring_wkt,
    _persist_children,
    _persist_snapshot,
)
from consorcio_fenix_scraper.domain import (
    DirectionMatchConfidence,
    DirectionMatchMethod,
    ParsedRoutePage,
    RouteDirection,
    RouteSnapshot,
    ScheduleEntry,
    ServiceDirection,
    ServiceDirectionMatch,
)
```

Update `Base.metadata.create_all` tables:

```python
        tables=[
            ScrapeRunRecord.__table__,
            RouteRecord.__table__,
            RouteVersionRecord.__table__,
            RouteDirectionRecord.__table__,
            ServiceDirectionRecord.__table__,
            ScheduleEntryRecord.__table__,
        ],
```

- [ ] **Step 2: Add failing persistence test**

Add this test before `test_linestring_wkt_uses_srid_4326_and_lon_lat_order`:

```python
def test_persist_children_creates_service_directions_and_schedule_links(db_session: Session):
    version, created = _persist_snapshot(db_session, uuid4(), _snapshot())
    assert created is True
    snapshot = RouteSnapshot(
        route=ParsedRoutePage(
            code="110",
            name="TICEN - TITRI",
            slug="ticen-titri",
            page_url="https://www.consorciofenix.com.br/horarios/ticen-titri,110",
            service_directions=[
                ServiceDirection(
                    sequence=1,
                    departure_label="Saída Bairro",
                    schedules=[
                        ScheduleEntry(day_type="Sábado", departure_label="Saída Bairro", time="06:00", flags=("E",))
                    ],
                ),
                ServiceDirection(
                    sequence=2,
                    departure_label="Saída TICEN",
                    schedules=[
                        ScheduleEntry(day_type="Sábado", departure_label="Saída TICEN", time="06:30", flags=("R",))
                    ],
                ),
            ],
        ),
        directions=[
            RouteDirection(name="VOLTA", coordinates=[(-48.55, -27.59), (-48.59, -27.58)]),
            RouteDirection(name="IDA", coordinates=[(-48.59, -27.58), (-48.55, -27.59)]),
        ],
        direction_matches=[
            ServiceDirectionMatch(
                service_direction_sequence=1,
                route_direction_sequence=2,
                confidence=DirectionMatchConfidence.MEDIUM,
                method=DirectionMatchMethod.LABEL_ORDER_IDA_VOLTA,
                notes={"departure_label": "Saída Bairro"},
            ),
            ServiceDirectionMatch(
                service_direction_sequence=2,
                route_direction_sequence=1,
                confidence=DirectionMatchConfidence.MEDIUM,
                method=DirectionMatchMethod.LABEL_ORDER_IDA_VOLTA,
                notes={"departure_label": "Saída TICEN"},
            ),
        ],
        source_hash="source-service",
        map_hash="map-service",
    )

    _persist_children(db_session, version.id, snapshot)

    service_rows = db_session.query(ServiceDirectionRecord).order_by(ServiceDirectionRecord.sequence).all()
    schedule_rows = db_session.query(ScheduleEntryRecord).order_by(ScheduleEntryRecord.time).all()
    route_direction_rows = db_session.query(RouteDirectionRecord).order_by(RouteDirectionRecord.sequence).all()

    assert [(row.sequence, row.departure_label, row.match_confidence, row.match_method) for row in service_rows] == [
        (1, "Saída Bairro", "medium", "label_order_ida_volta"),
        (2, "Saída TICEN", "medium", "label_order_ida_volta"),
    ]
    assert service_rows[0].route_direction_id == route_direction_rows[1].id
    assert service_rows[1].route_direction_id == route_direction_rows[0].id
    assert [(row.time, row.departure_label, row.service_direction_id) for row in schedule_rows] == [
        ("06:00", "Saída Bairro", service_rows[0].id),
        ("06:30", "Saída TICEN", service_rows[1].id),
    ]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_persistence.py::test_persist_children_creates_service_directions_and_schedule_links -v`

Expected: FAIL because `ServiceDirectionRecord` does not exist.

- [ ] **Step 4: Add SQLite-safe geometry variants and SQLAlchemy model**

Add these constants after `JSON_TYPE` in `db.py` so persistence tests can create geometry tables in SQLite while PostgreSQL still uses PostGIS types:

```python
LINESTRING_TYPE = Geometry("LINESTRING", srid=4326).with_variant(Text, "sqlite")
POINT_TYPE = Geometry("POINT", srid=4326).with_variant(Text, "sqlite")
```

Update geometry columns:

```python
    geometry: Mapped[object] = mapped_column(LINESTRING_TYPE)
```

```python
    geometry: Mapped[object | None] = mapped_column(POINT_TYPE)
```

Add this class after `RouteDirectionRecord` in `db.py`:

```python
class ServiceDirectionRecord(Base):
    __tablename__ = "service_directions"
    __table_args__ = (
        UniqueConstraint(
            "route_version_id",
            "departure_label",
            name="uq_service_directions_route_version_departure_label",
        ),
    )

    id: Mapped[PyUUID] = _uuid_pk()
    route_version_id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("route_versions.id"), index=True)
    route_direction_id: Mapped[PyUUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("route_directions.id"),
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer)
    departure_label: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str | None] = mapped_column(Text)
    direction_kind: Mapped[str | None] = mapped_column(Text)
    match_confidence: Mapped[str] = mapped_column(String(16))
    match_method: Mapped[str] = mapped_column(String(64))
    match_notes: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
```

Update `ScheduleEntryRecord`:

```python
    service_direction_id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("service_directions.id"),
        index=True,
    )
```

- [ ] **Step 5: Update child persistence**

Replace `_persist_children` with:

```python
def _persist_children(session: Session, route_version_id: PyUUID, snapshot: RouteSnapshot) -> None:
    route_direction_records: dict[int, RouteDirectionRecord] = {}
    for index, direction in enumerate(snapshot.directions, start=1):
        record = RouteDirectionRecord(
            route_version_id=route_version_id,
            name=direction.name,
            sequence=index,
            geometry=_linestring_wkt(direction),
        )
        session.add(record)
        route_direction_records[index] = record
    session.flush()

    matches_by_service_sequence = {
        match.service_direction_sequence: match for match in snapshot.direction_matches
    }
    service_direction_records: dict[int, ServiceDirectionRecord] = {}
    for service_direction in snapshot.route.service_directions:
        match = matches_by_service_sequence.get(service_direction.sequence)
        route_direction_id = None
        match_confidence = "none"
        match_method = "unmatched"
        match_notes: dict = {}
        if match is not None:
            match_confidence = match.confidence.value
            match_method = match.method.value
            match_notes = match.notes
            if match.route_direction_sequence is not None:
                route_direction = route_direction_records.get(match.route_direction_sequence)
                route_direction_id = route_direction.id if route_direction is not None else None

        record = ServiceDirectionRecord(
            route_version_id=route_version_id,
            route_direction_id=route_direction_id,
            sequence=service_direction.sequence,
            departure_label=service_direction.departure_label,
            normalized_name=service_direction.normalized_name,
            direction_kind=service_direction.direction_kind,
            match_confidence=match_confidence,
            match_method=match_method,
            match_notes=match_notes,
        )
        session.add(record)
        service_direction_records[service_direction.sequence] = record
    session.flush()

    for service_direction in snapshot.route.service_directions:
        service_record = service_direction_records[service_direction.sequence]
        for entry in service_direction.schedules:
            session.add(
                ScheduleEntryRecord(
                    route_version_id=route_version_id,
                    service_direction_id=service_record.id,
                    day_type=entry.day_type,
                    departure_label=entry.departure_label,
                    time=entry.time,
                    flags=list(entry.flags),
                )
            )
    for step in snapshot.route.itinerary_steps:
        session.add(ItineraryStepRecord(route_version_id=route_version_id, sequence=step.sequence, name=step.name))
```

- [ ] **Step 6: Run persistence tests**

Run: `uv run pytest tests/test_persistence.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/consorcio_fenix_scraper/db.py tests/test_persistence.py
git commit -m "feat: persist service directions"
```

## Task 6: Migration Schema

**Files:**
- Modify: `migrations/versions/20260502_0001_initial_postgis_schema.py`

- [ ] **Step 1: Add service directions table after route directions**

In `upgrade`, after creating `route_directions`, add:

```python
    op.create_table(
        "service_directions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_direction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("departure_label", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=True),
        sa.Column("direction_kind", sa.Text(), nullable=True),
        sa.Column("match_confidence", sa.String(length=16), nullable=False),
        sa.Column("match_method", sa.String(length=64), nullable=False),
        sa.Column("match_notes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["route_direction_id"], ["route_directions.id"]),
        sa.ForeignKeyConstraint(["route_version_id"], ["route_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "route_version_id",
            "departure_label",
            name="uq_service_directions_route_version_departure_label",
        ),
    )
    op.create_index(
        op.f("ix_service_directions_route_direction_id"),
        "service_directions",
        ["route_direction_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_service_directions_route_version_id"),
        "service_directions",
        ["route_version_id"],
        unique=False,
    )
```

- [ ] **Step 2: Add schedule FK column and index**

In `schedule_entries` table creation, add this column after `route_version_id`:

```python
        sa.Column("service_direction_id", postgresql.UUID(as_uuid=True), nullable=False),
```

Add the FK:

```python
        sa.ForeignKeyConstraint(["service_direction_id"], ["service_directions.id"]),
```

After `ix_schedule_entries_route_version_id`, add:

```python
    op.create_index(
        op.f("ix_schedule_entries_service_direction_id"),
        "schedule_entries",
        ["service_direction_id"],
        unique=False,
    )
```

- [ ] **Step 3: Update downgrade order**

In `downgrade`, drop the new schedule index before dropping `schedule_entries`:

```python
    op.drop_index(op.f("ix_schedule_entries_service_direction_id"), table_name="schedule_entries")
```

After dropping `schedule_entries`, drop service direction indexes and table:

```python
    op.drop_index(op.f("ix_service_directions_route_version_id"), table_name="service_directions")
    op.drop_index(op.f("ix_service_directions_route_direction_id"), table_name="service_directions")
    op.drop_table("service_directions")
```

- [ ] **Step 4: Run full tests**

Run: `uv run pytest -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/20260502_0001_initial_postgis_schema.py
git commit -m "feat: add service directions schema"
```

## Task 7: Final Verification

**Files:**
- Review: `README.md`
- Review: `docs/superpowers/specs/2026-05-02-service-directions-design.md`

- [ ] **Step 1: Run targeted parser, inference, persistence, and CLI tests**

Run:

```bash
uv run pytest tests/test_parsers.py tests/test_directions.py tests/test_persistence.py tests/test_cli.py -v
```

Expected: PASS.

- [ ] **Step 2: Run full suite**

Run:

```bash
uv run pytest -v
```

Expected: PASS.

- [ ] **Step 3: Inspect final diff**

Run:

```bash
git status --short
git log --oneline -5
```

Expected: no uncommitted changes, and recent commits for domain/parser, inference, CLI snapshot matching, persistence, and migration.

## Self-Review

- Spec coverage: The plan covers explicit schedule groups, KML geometry preservation, inferred low-confidence links, persistence metadata, downstream join path, and tests for parser/inference/persistence.
- Red-flag scan: no forbidden planning tokens, vague implementation steps, or reference-only steps remain.
- Type consistency: `ServiceDirection`, `ServiceDirectionMatch`, `DirectionMatchConfidence`, and `DirectionMatchMethod` are introduced before use; persistence uses route-direction sequence numbers from snapshot matches and resolves them to database IDs after flushing KML records.

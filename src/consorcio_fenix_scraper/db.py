from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from hashlib import sha256
from time import perf_counter
from typing import NamedTuple
from uuid import UUID as PyUUID, uuid4

from geoalchemy2 import Geometry
from sqlalchemy import (
    and_,
    Boolean,
    case,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    create_engine,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, insert as postgresql_insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from consorcio_fenix_scraper.domain import (
    DirectionMatchConfidence,
    DirectionMatchMethod,
    FarePolicy,
    RouteDirection,
    RouteSnapshot,
    RouteSegmentRebuildResult,
    ScrapeRunResult,
    ScrapeStatus,
)
from consorcio_fenix_scraper.logging import get_logger
from consorcio_fenix_scraper.segments import materialize_route_segments


logger = get_logger(__name__)


class Base(DeclarativeBase):
    pass


JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class ChildRows(NamedTuple):
    route_directions: list[dict]
    route_segments: list[dict]
    service_directions: list[dict]
    schedule_entries: list[dict]
    itinerary_steps: list[dict]


class PreparedSnapshot(NamedTuple):
    snapshot: RouteSnapshot
    proposed_version_id: PyUUID
    child_rows: ChildRows
    row_count: int


def _uuid_pk():
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)


def _geometry_type(geometry_type: str):
    return Text().with_variant(Geometry(geometry_type, srid=4326), "postgresql")


class ScrapeRunRecord(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[PyUUID] = _uuid_pk()
    source_url: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default=ScrapeStatus.RUNNING.value)
    error_summary: Mapped[str | None] = mapped_column(Text)


class FareVersionRecord(Base):
    __tablename__ = "fare_versions"
    __table_args__ = (
        UniqueConstraint("region", "source_hash", name="uq_fare_versions_region_source_hash"),
        Index("ix_fare_versions_region_is_current", "region", "is_current"),
    )

    id: Mapped[PyUUID] = _uuid_pk()
    region: Mapped[str] = mapped_column(Text, index=True)
    citizen_card_cents: Mapped[int | None] = mapped_column(Integer)
    vt_tourist_card_cents: Mapped[int | None] = mapped_column(Integer)
    cash_qrcode_pix_cents: Mapped[int | None] = mapped_column(Integer)
    source_hash: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class RouteRecord(Base):
    __tablename__ = "routes"

    id: Mapped[PyUUID] = _uuid_pk()
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    fare_region: Mapped[str | None] = mapped_column(Text)
    last_changed: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)

    versions: Mapped[list["RouteVersionRecord"]] = relationship(back_populates="route")


class RouteVersionRecord(Base):
    __tablename__ = "route_versions"
    __table_args__ = (
        UniqueConstraint(
            "route_id",
            "source_hash",
            "map_hash",
            name="uq_route_versions_route_source_map_hash",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[PyUUID] = _uuid_pk()
    route_id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("routes.id"), index=True)
    scrape_run_id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("scrape_runs.id"), index=True)
    fare_version_id: Mapped[PyUUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("fare_versions.id"), index=True)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    map_hash: Mapped[str | None] = mapped_column(String(64))
    page_url: Mapped[str] = mapped_column(Text)
    map_url: Mapped[str | None] = mapped_column(Text)
    snapshot: Mapped[dict] = mapped_column(JSON_TYPE)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    route: Mapped[RouteRecord] = relationship(back_populates="versions")


class RouteDirectionRecord(Base):
    __tablename__ = "route_directions"

    id: Mapped[PyUUID] = _uuid_pk()
    route_version_id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("route_versions.id"), index=True)
    name: Mapped[str] = mapped_column(Text)
    sequence: Mapped[int] = mapped_column(Integer)
    geometry: Mapped[object] = mapped_column(_geometry_type("LINESTRING"))


class RouteSegmentRecord(Base):
    __tablename__ = "route_segments"
    __table_args__ = (
        UniqueConstraint(
            "route_version_id",
            "route_direction_id",
            "sequence",
            name="uq_route_segments_route_version_direction_sequence",
        ),
        Index("ix_route_segments_geometry", "geometry", postgresql_using="gist"),
        Index(
            "ix_route_segments_route_version_direction_sequence",
            "route_version_id",
            "route_direction_id",
            "sequence",
        ),
    )

    id: Mapped[PyUUID] = _uuid_pk()
    route_version_id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("route_versions.id"), index=True)
    route_direction_id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("route_directions.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    source_segment_sequence: Mapped[int] = mapped_column(Integer)
    source_fraction_start: Mapped[float] = mapped_column(Float)
    source_fraction_end: Mapped[float] = mapped_column(Float)
    geometry: Mapped[object] = mapped_column(_geometry_type("LINESTRING"))
    bearing_degrees: Mapped[float] = mapped_column(Float)
    distance_meters: Mapped[float] = mapped_column(Float)
    cumulative_distance_meters: Mapped[float] = mapped_column(Float)


class ServiceDirectionRecord(Base):
    __tablename__ = "service_directions"
    __table_args__ = (UniqueConstraint("route_version_id", "departure_label", name="uq_service_directions_route_version_departure_label"),)

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
    confidence: Mapped[str] = mapped_column(String(16), default=DirectionMatchConfidence.NONE.value)
    method: Mapped[str] = mapped_column(String(32), default=DirectionMatchMethod.UNMATCHED.value)
    notes: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)


class ScheduleEntryRecord(Base):
    __tablename__ = "schedule_entries"

    id: Mapped[PyUUID] = _uuid_pk()
    route_version_id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("route_versions.id"), index=True)
    service_direction_id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("service_directions.id"),
        index=True,
    )
    day_type: Mapped[str] = mapped_column(Text)
    departure_label: Mapped[str] = mapped_column(Text)
    time: Mapped[str] = mapped_column(String(5))
    flags: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)


class ItineraryStepRecord(Base):
    __tablename__ = "itinerary_steps"

    id: Mapped[PyUUID] = _uuid_pk()
    route_version_id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("route_versions.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)


class StopRecord(Base):
    __tablename__ = "stops"

    id: Mapped[PyUUID] = _uuid_pk()
    external_id: Mapped[str | None] = mapped_column(Text, index=True)
    name: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    geometry: Mapped[object | None] = mapped_column(_geometry_type("POINT"))


class RawPageRecord(Base):
    __tablename__ = "raw_pages"
    __table_args__ = (UniqueConstraint("scrape_run_id", "url", name="uq_raw_page_run_url"),)

    id: Mapped[PyUUID] = _uuid_pk()
    scrape_run_id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("scrape_runs.id"), index=True)
    url: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)


def make_engine(database_url: str):
    return create_engine(database_url, future=True)


def make_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(make_engine(database_url), expire_on_commit=False)


def persist_snapshots(
    session_factory: sessionmaker[Session],
    source_url: str,
    snapshots: Iterable[RouteSnapshot],
    *,
    max_batch_rows: int = 10_000,
) -> ScrapeRunResult:
    if max_batch_rows < 1:
        raise ValueError("max_batch_rows must be greater than zero")

    started = perf_counter()
    run_id = _create_scrape_run(session_factory, source_url)
    result = ScrapeRunResult()

    try:
        proposed_rows = 0
        for batch_number, (batch, batch_rows) in enumerate(
            _batch_prepared_snapshots(snapshots, max_batch_rows),
            start=1,
        ):
            proposed_rows += batch_rows
            batch_started = perf_counter()
            try:
                with session_factory.begin() as session:
                    batch_result = _persist_data_batch(session, run_id, batch)
            except Exception:
                batch_duration = perf_counter() - batch_started
                logger.exception(
                    "persistence_batch_failed scrape_run_id=%s batch=%s routes=%s proposed_rows=%s "
                    "duration_seconds=%.3f rows_per_second=%.2f",
                    run_id,
                    batch_number,
                    len(batch),
                    batch_rows,
                    batch_duration,
                    _throughput(batch_rows, batch_duration),
                )
                raise
            batch_duration = perf_counter() - batch_started
            _add_result(result, batch_result)
            logger.info(
                "persistence_batch_complete scrape_run_id=%s batch=%s routes=%s proposed_rows=%s "
                "duration_seconds=%.3f rows_per_second=%.2f",
                run_id,
                batch_number,
                len(batch),
                batch_rows,
                batch_duration,
                _throughput(batch_rows, batch_duration),
            )
        _finish_scrape_run(session_factory, run_id, ScrapeStatus.SUCCESS)
    except Exception as exc:
        try:
            _finish_scrape_run(session_factory, run_id, ScrapeStatus.FAILED, error_summary=str(exc))
        except Exception:
            logger.exception("Retrying failed scrape run finalization id=%s", run_id)
            _finish_scrape_run(session_factory, run_id, ScrapeStatus.FAILED, error_summary=str(exc))
        logger.exception("Scrape run id=%s failed: %s", run_id, exc)
        raise

    duration = perf_counter() - started
    logger.info(
        "persistence_complete scrape_run_id=%s status=%s routes=%s proposed_rows=%s "
        "duration_seconds=%.3f rows_per_second=%.2f",
        run_id,
        ScrapeStatus.SUCCESS.value,
        result.routes,
        proposed_rows,
        duration,
        _throughput(proposed_rows, duration),
    )
    return result


def _create_scrape_run(session_factory: sessionmaker[Session], source_url: str) -> PyUUID:
    with session_factory.begin() as session:
        run = ScrapeRunRecord(source_url=source_url, status=ScrapeStatus.RUNNING.value)
        session.add(run)
        session.flush()
        run_id = run.id
    logger.info("Created scrape run id=%s source_url=%s", run_id, source_url)
    return run_id


def _finish_scrape_run(
    session_factory: sessionmaker[Session],
    run_id: PyUUID,
    status: ScrapeStatus,
    *,
    error_summary: str | None = None,
) -> None:
    with session_factory.begin() as session:
        run = session.get(ScrapeRunRecord, run_id)
        if run is None:
            raise RuntimeError(f"Scrape run id={run_id} no longer exists")
        run.status = status.value
        run.error_summary = error_summary
        run.finished_at = datetime.now(UTC)


def _prepare_snapshot(snapshot: RouteSnapshot) -> PreparedSnapshot:
    proposed_version_id = uuid4()
    child_rows = _materialize_child_rows(proposed_version_id, snapshot)
    metadata_rows = 2 + int(snapshot.route.fare_policy is not None)
    row_count = metadata_rows + sum(len(rows) for rows in child_rows)
    return PreparedSnapshot(snapshot, proposed_version_id, child_rows, row_count)


def _batch_prepared_snapshots(
    snapshots: Iterable[RouteSnapshot],
    max_rows: int,
) -> Iterable[tuple[list[PreparedSnapshot], int]]:
    if max_rows < 1:
        raise ValueError("max_rows must be greater than zero")

    batch: list[PreparedSnapshot] = []
    batch_rows = 0
    for snapshot in snapshots:
        prepared = _prepare_snapshot(snapshot)
        if batch and batch_rows + prepared.row_count > max_rows:
            yield batch, batch_rows
            batch = []
            batch_rows = 0
        batch.append(prepared)
        batch_rows += prepared.row_count
        if prepared.row_count > max_rows:
            yield batch, batch_rows
            batch = []
            batch_rows = 0
    if batch:
        yield batch, batch_rows


def _throughput(row_count: int, duration: float) -> float:
    return row_count / duration if duration > 0 else 0.0


def _add_result(target: ScrapeRunResult, increment: ScrapeRunResult) -> None:
    target.routes += increment.routes
    target.schedules += increment.schedules
    target.geometries += increment.geometries
    target.itinerary_steps += increment.itinerary_steps
    target.stops += increment.stops
    target.warnings.extend(increment.warnings)
    target.failures.extend(increment.failures)


def _persist_data_batch(session: Session, run_id: PyUUID, prepared_snapshots: list[PreparedSnapshot]) -> ScrapeRunResult:
    result = ScrapeRunResult()
    snapshots = [prepared.snapshot for prepared in prepared_snapshots]
    proposed_version_ids = [prepared.proposed_version_id for prepared in prepared_snapshots]
    reconciled_versions = _persist_snapshot_batch(session, run_id, snapshots, proposed_version_ids)
    new_versions: list[PreparedSnapshot] = []
    for prepared, (version, created) in zip(prepared_snapshots, reconciled_versions, strict=True):
        snapshot = prepared.snapshot
        result.routes += 1
        result.schedules += len(snapshot.route.schedules)
        result.geometries += len(snapshot.directions)
        result.itinerary_steps += len(snapshot.route.itinerary_steps)
        if created:
            new_versions.append(prepared)
        logger.info("Persisted route %s version id=%s", snapshot.route.code, version.id)
        logger.debug(
            "Persisted route %s counts: schedules=%s directions=%s itinerary_steps=%s source_hash=%s map_hash=%s",
            snapshot.route.code,
            len(snapshot.route.schedules),
            len(snapshot.directions),
            len(snapshot.route.itinerary_steps),
            snapshot.source_hash,
            snapshot.map_hash,
        )
    _persist_children(session, new_versions)
    return result


class RouteVersionKey(NamedTuple):
    route_id: PyUUID
    source_hash: str
    map_hash: str | None


class FareVersionKey(NamedTuple):
    region: str
    source_hash: str


def _persist_snapshot_batch(
    session: Session,
    run_id: PyUUID,
    snapshots: list[RouteSnapshot],
    proposed_version_ids: list[PyUUID],
) -> list[tuple[RouteVersionRecord, bool]]:
    if not snapshots:
        return []

    route_ids = _reconcile_routes(session, snapshots)
    fare_version_ids = _reconcile_fare_versions(session, snapshots)
    return _reconcile_route_versions(
        session,
        run_id,
        snapshots,
        proposed_version_ids,
        route_ids,
        fare_version_ids,
    )


def _reconcile_routes(session: Session, snapshots: list[RouteSnapshot]) -> dict[str, PyUUID]:
    latest_by_code = {snapshot.route.code: snapshot for snapshot in snapshots}
    codes = list(latest_by_code)

    if session.get_bind().dialect.name == "postgresql":
        stored_ids = dict(session.execute(select(RouteRecord.code, RouteRecord.id).where(RouteRecord.code.in_(codes))))
        rows = [_route_values(snapshot, stored_ids.get(code, uuid4())) for code, snapshot in latest_by_code.items()]
        return dict(session.execute(_postgresql_route_upsert(rows)))

    stored_routes = {
        route.code: route for route in session.scalars(select(RouteRecord).where(RouteRecord.code.in_(codes)))
    }
    for code, snapshot in latest_by_code.items():
        route = stored_routes.get(code)
        if route is None:
            route = RouteRecord(**_route_values(snapshot, uuid4()))
            stored_routes[code] = route
            session.add(route)
        else:
            values = _route_values(snapshot, route.id)
            for name, value in values.items():
                if name != "id":
                    setattr(route, name, value)
    session.flush()
    return {code: route.id for code, route in stored_routes.items()}


def _route_values(snapshot: RouteSnapshot, route_id: PyUUID) -> dict:
    route = snapshot.route
    return {
        "id": route_id,
        "code": route.code,
        "name": route.name,
        "slug": route.slug,
        "category": route.category,
        "fare_region": route.fare_region,
        "last_changed": route.last_changed,
        "is_current": True,
    }


def _postgresql_route_upsert(rows: list[dict]):
    statement = postgresql_insert(RouteRecord).values(rows)
    excluded = statement.excluded
    return statement.on_conflict_do_update(
        index_elements=[RouteRecord.code],
        set_={
            "name": excluded.name,
            "slug": excluded.slug,
            "category": excluded.category,
            "fare_region": excluded.fare_region,
            "last_changed": excluded.last_changed,
            "is_current": excluded.is_current,
        },
    ).returning(RouteRecord.code, RouteRecord.id)


def _reconcile_fare_versions(session: Session, snapshots: list[RouteSnapshot]) -> dict[FareVersionKey, PyUUID]:
    fare_inputs: dict[FareVersionKey, tuple[FarePolicy, str]] = {}
    current_key_by_region: dict[str, FareVersionKey] = {}
    for snapshot in snapshots:
        fare_policy = snapshot.route.fare_policy
        if fare_policy is None:
            continue
        key = FareVersionKey(fare_policy.region, _fare_policy_hash(fare_policy))
        fare_inputs.setdefault(key, (fare_policy, snapshot.route.page_url))
        current_key_by_region[fare_policy.region] = key

    if not fare_inputs:
        return {}

    regions = list(current_key_by_region)
    fare_identity_predicate = or_(
        *(
            and_(FareVersionRecord.region == key.region, FareVersionRecord.source_hash == key.source_hash)
            for key in fare_inputs
        )
    )
    stored_fares = list(session.scalars(select(FareVersionRecord).where(fare_identity_predicate)))
    stored_ids = {FareVersionKey(fare.region, fare.source_hash): fare.id for fare in stored_fares}

    if session.get_bind().dialect.name == "postgresql":
        rows = [
            _fare_version_values(fare_policy, source_url, stored_ids.get(key, uuid4()))
            for key, (fare_policy, source_url) in fare_inputs.items()
        ]
        canonical_ids = {
            FareVersionKey(region, source_hash): fare_id
            for region, source_hash, fare_id in session.execute(_postgresql_fare_version_upsert(rows))
        }
        session.execute(
            update(FareVersionRecord).where(FareVersionRecord.region.in_(regions)).values(is_current=False)
        )
        current_ids = [canonical_ids[key] for key in current_key_by_region.values()]
        session.execute(update(FareVersionRecord).where(FareVersionRecord.id.in_(current_ids)).values(is_current=True))
        return canonical_ids

    by_key = {FareVersionKey(fare.region, fare.source_hash): fare for fare in stored_fares}
    for key, (fare_policy, source_url) in fare_inputs.items():
        if key not in by_key:
            fare = FareVersionRecord(**_fare_version_values(fare_policy, source_url, uuid4()))
            by_key[key] = fare
            stored_fares.append(fare)
            session.add(fare)
    session.execute(update(FareVersionRecord).where(FareVersionRecord.region.in_(regions)).values(is_current=False))
    current_keys = set(current_key_by_region.values())
    for fare in stored_fares:
        fare.is_current = FareVersionKey(fare.region, fare.source_hash) in current_keys
    session.flush()
    return {key: fare.id for key, fare in by_key.items()}


def _fare_version_values(fare_policy: FarePolicy, source_url: str, fare_version_id: PyUUID) -> dict:
    return {
        "id": fare_version_id,
        "region": fare_policy.region,
        "citizen_card_cents": fare_policy.citizen_card_cents,
        "vt_tourist_card_cents": fare_policy.vt_tourist_card_cents,
        "cash_qrcode_pix_cents": fare_policy.cash_qrcode_pix_cents,
        "source_hash": _fare_policy_hash(fare_policy),
        "source_url": source_url,
        "is_current": True,
    }


def _postgresql_fare_version_upsert(rows: list[dict]):
    statement = postgresql_insert(FareVersionRecord).values(rows)
    excluded = statement.excluded
    return statement.on_conflict_do_update(
        constraint="uq_fare_versions_region_source_hash",
        set_={"is_current": excluded.is_current},
    ).returning(FareVersionRecord.region, FareVersionRecord.source_hash, FareVersionRecord.id)


def _reconcile_route_versions(
    session: Session,
    run_id: PyUUID,
    snapshots: list[RouteSnapshot],
    proposed_version_ids: list[PyUUID],
    route_ids: dict[str, PyUUID],
    fare_version_ids: dict[FareVersionKey, PyUUID],
) -> list[tuple[RouteVersionRecord, bool]]:
    affected_route_ids = list({route_ids[snapshot.route.code] for snapshot in snapshots})
    proposed_keys = {_snapshot_route_version_key(snapshot, route_ids) for snapshot in snapshots}
    identity_predicate = _route_version_identity_predicate(proposed_keys)
    stored_versions = list(
        session.scalars(select(RouteVersionRecord).where(identity_predicate))
    )
    by_key = {_stored_route_version_key(version): version for version in stored_versions}
    proposed_by_key: dict[RouteVersionKey, tuple[PyUUID, RouteSnapshot, PyUUID | None]] = {}
    for snapshot, proposed_version_id in zip(snapshots, proposed_version_ids, strict=True):
        key = _snapshot_route_version_key(snapshot, route_ids)
        proposed_by_key.setdefault(
            key,
            (proposed_version_id, snapshot, _fare_version_id(snapshot, fare_version_ids)),
        )

    new_keys = set(proposed_by_key) - set(by_key)
    if session.get_bind().dialect.name == "postgresql":
        inserted_keys = _insert_postgresql_route_versions(session, run_id, proposed_by_key, new_keys)
        stored_versions = list(
            session.scalars(select(RouteVersionRecord).where(identity_predicate))
        )
        by_key = {_stored_route_version_key(version): version for version in stored_versions}
        new_keys = inserted_keys
        _update_postgresql_route_versions(session, snapshots, route_ids, fare_version_ids, by_key)
    else:
        for key in new_keys:
            version_id, snapshot, fare_version_id = proposed_by_key[key]
            version = RouteVersionRecord(
                **_route_version_values(version_id, run_id, snapshot, route_ids[snapshot.route.code], fare_version_id)
            )
            by_key[key] = version
            stored_versions.append(version)
            session.add(version)
        session.execute(
            update(RouteVersionRecord)
            .where(RouteVersionRecord.route_id.in_(affected_route_ids))
            .values(is_current=False)
        )
        for snapshot in snapshots:
            key = _snapshot_route_version_key(snapshot, route_ids)
            by_key[key].fare_version_id = _fare_version_id(snapshot, fare_version_ids)
        for snapshot in {snapshot.route.code: snapshot for snapshot in snapshots}.values():
            key = _snapshot_route_version_key(snapshot, route_ids)
            by_key[key].is_current = True
        session.flush()

    results: list[tuple[RouteVersionRecord, bool]] = []
    emitted_new_keys: set[RouteVersionKey] = set()
    for snapshot in snapshots:
        key = _snapshot_route_version_key(snapshot, route_ids)
        created = key in new_keys and key not in emitted_new_keys
        results.append((by_key[key], created))
        if created:
            emitted_new_keys.add(key)
    return results


def _insert_postgresql_route_versions(
    session: Session,
    run_id: PyUUID,
    proposed_by_key: dict[RouteVersionKey, tuple[PyUUID, RouteSnapshot, PyUUID | None]],
    new_keys: set[RouteVersionKey],
) -> set[RouteVersionKey]:
    if not new_keys:
        return set()
    rows = [
        _route_version_values(version_id, run_id, snapshot, key.route_id, fare_version_id)
        for key, (version_id, snapshot, fare_version_id) in proposed_by_key.items()
        if key in new_keys
    ]
    return {
        RouteVersionKey(route_id, source_hash, map_hash)
        for route_id, source_hash, map_hash in session.execute(_postgresql_route_version_insert(rows))
    }


def _postgresql_route_version_insert(rows: list[dict]):
    return (
        postgresql_insert(RouteVersionRecord)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_route_versions_route_source_map_hash")
        .returning(
            RouteVersionRecord.route_id,
            RouteVersionRecord.source_hash,
            RouteVersionRecord.map_hash,
        )
    )


def _update_postgresql_route_versions(
    session: Session,
    snapshots: list[RouteSnapshot],
    route_ids: dict[str, PyUUID],
    fare_version_ids: dict[FareVersionKey, PyUUID],
    by_key: dict[RouteVersionKey, RouteVersionRecord],
) -> None:
    affected_route_ids = list({route_ids[snapshot.route.code] for snapshot in snapshots})
    session.execute(
        update(RouteVersionRecord)
        .where(RouteVersionRecord.route_id.in_(affected_route_ids))
        .values(is_current=False)
    )
    fare_id_by_version_id: dict[PyUUID, PyUUID | None] = {}
    for snapshot in snapshots:
        key = _snapshot_route_version_key(snapshot, route_ids)
        fare_id_by_version_id[by_key[key].id] = _fare_version_id(snapshot, fare_version_ids)
    session.execute(
        update(RouteVersionRecord)
        .where(RouteVersionRecord.id.in_(fare_id_by_version_id))
        .values(fare_version_id=case(fare_id_by_version_id, value=RouteVersionRecord.id))
    )
    latest_by_code = {snapshot.route.code: snapshot for snapshot in snapshots}
    current_ids = [
        by_key[_snapshot_route_version_key(snapshot, route_ids)].id for snapshot in latest_by_code.values()
    ]
    session.execute(update(RouteVersionRecord).where(RouteVersionRecord.id.in_(current_ids)).values(is_current=True))


def _route_version_values(
    version_id: PyUUID,
    run_id: PyUUID,
    snapshot: RouteSnapshot,
    route_id: PyUUID,
    fare_version_id: PyUUID | None,
) -> dict:
    return {
        "id": version_id,
        "route_id": route_id,
        "scrape_run_id": run_id,
        "fare_version_id": fare_version_id,
        "source_hash": snapshot.source_hash,
        "map_hash": snapshot.map_hash,
        "page_url": snapshot.route.page_url,
        "map_url": snapshot.route.map_url,
        "snapshot": snapshot.model_dump(mode="json"),
        "is_current": True,
    }


def _snapshot_route_version_key(
    snapshot: RouteSnapshot,
    route_ids: dict[str, PyUUID],
) -> RouteVersionKey:
    return RouteVersionKey(route_ids[snapshot.route.code], snapshot.source_hash, snapshot.map_hash)


def _stored_route_version_key(version: RouteVersionRecord) -> RouteVersionKey:
    return RouteVersionKey(version.route_id, version.source_hash, version.map_hash)


def _route_version_identity_predicate(keys: set[RouteVersionKey]):
    return or_(
        *(
            and_(
                RouteVersionRecord.route_id == key.route_id,
                RouteVersionRecord.source_hash == key.source_hash,
                RouteVersionRecord.map_hash.is_not_distinct_from(key.map_hash),
            )
            for key in keys
        )
    )


def _fare_version_id(
    snapshot: RouteSnapshot,
    fare_version_ids: dict[FareVersionKey, PyUUID],
) -> PyUUID | None:
    fare_policy = snapshot.route.fare_policy
    if fare_policy is None:
        return None
    return fare_version_ids[FareVersionKey(fare_policy.region, _fare_policy_hash(fare_policy))]


def _fare_policy_hash(fare_policy: FarePolicy) -> str:
    payload = json.dumps(fare_policy.model_dump(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def _persist_children(session: Session, new_versions: list[PreparedSnapshot]) -> None:
    child_rows = ChildRows([], [], [], [], [])
    for prepared in new_versions:
        child_rows.route_directions.extend(prepared.child_rows.route_directions)
        child_rows.route_segments.extend(prepared.child_rows.route_segments)
        child_rows.service_directions.extend(prepared.child_rows.service_directions)
        child_rows.schedule_entries.extend(prepared.child_rows.schedule_entries)
        child_rows.itinerary_steps.extend(prepared.child_rows.itinerary_steps)

    _execute_bulk_insert(session, RouteDirectionRecord, child_rows.route_directions)
    _execute_bulk_insert(session, RouteSegmentRecord, child_rows.route_segments)
    _execute_bulk_insert(session, ServiceDirectionRecord, child_rows.service_directions)
    _execute_bulk_insert(session, ScheduleEntryRecord, child_rows.schedule_entries)
    _execute_bulk_insert(session, ItineraryStepRecord, child_rows.itinerary_steps)


def _materialize_child_rows(route_version_id: PyUUID, snapshot: RouteSnapshot) -> ChildRows:
    route_direction_rows: list[dict] = []
    route_direction_id_by_sequence: dict[int, PyUUID] = {}
    for index, direction in enumerate(snapshot.directions, start=1):
        route_direction_id = uuid4()
        route_direction_rows.append(
            {
                "id": route_direction_id,
                "route_version_id": route_version_id,
                "name": direction.name,
                "sequence": index,
                "geometry": _linestring_wkt(direction),
            }
        )
        route_direction_id_by_sequence[index] = route_direction_id

    route_segment_rows: list[dict] = []
    for index, direction in enumerate(snapshot.directions, start=1):
        for segment in materialize_route_segments(direction):
            route_segment_rows.append(
                {
                    "id": uuid4(),
                    "route_version_id": route_version_id,
                    "route_direction_id": route_direction_id_by_sequence[index],
                    "sequence": segment.sequence,
                    "source_segment_sequence": segment.source_segment_sequence,
                    "source_fraction_start": segment.source_fraction_start,
                    "source_fraction_end": segment.source_fraction_end,
                    "geometry": _segment_linestring_wkt(segment.coordinates),
                    "bearing_degrees": segment.bearing_degrees,
                    "distance_meters": segment.distance_meters,
                    "cumulative_distance_meters": segment.cumulative_distance_meters,
                }
            )

    matches_by_service_sequence = {match.service_direction_sequence: match for match in snapshot.direction_matches}
    service_direction_rows: list[dict] = []
    service_direction_id_by_sequence: dict[int, PyUUID] = {}
    for service_direction in sorted(snapshot.route.service_directions, key=lambda service: service.sequence):
        match = matches_by_service_sequence.get(service_direction.sequence)
        route_direction_id = (
            route_direction_id_by_sequence.get(match.route_direction_sequence)
            if match is not None and match.route_direction_sequence is not None
            else None
        )
        service_direction_id = uuid4()
        service_direction_rows.append(
            {
                "id": service_direction_id,
                "route_version_id": route_version_id,
                "route_direction_id": route_direction_id,
                "sequence": service_direction.sequence,
                "departure_label": service_direction.departure_label,
                "normalized_name": service_direction.normalized_name,
                "direction_kind": service_direction.direction_kind,
                "confidence": (match.confidence.value if match is not None else DirectionMatchConfidence.NONE.value),
                "method": (match.method.value if match is not None else DirectionMatchMethod.UNMATCHED.value),
                "notes": dict(match.notes) if match is not None else {},
            }
        )
        service_direction_id_by_sequence[service_direction.sequence] = service_direction_id

    schedule_entry_rows: list[dict] = []
    for service_direction in snapshot.route.service_directions:
        service_direction_id = service_direction_id_by_sequence[service_direction.sequence]
        for entry in service_direction.schedules:
            schedule_entry_rows.append(
                {
                    "id": uuid4(),
                    "route_version_id": route_version_id,
                    "service_direction_id": service_direction_id,
                    "day_type": entry.day_type,
                    "departure_label": entry.departure_label,
                    "time": entry.time,
                    "flags": list(entry.flags),
                }
            )

    itinerary_step_rows = [
        {
            "id": uuid4(),
            "route_version_id": route_version_id,
            "sequence": step.sequence,
            "name": step.name,
        }
        for step in snapshot.route.itinerary_steps
    ]

    return ChildRows(
        route_direction_rows,
        route_segment_rows,
        service_direction_rows,
        schedule_entry_rows,
        itinerary_step_rows,
    )


def _execute_bulk_insert(session: Session, record_type: type[Base], rows: list[dict]) -> None:
    if rows:
        session.execute(_bulk_insert_statement(record_type), rows)


def _bulk_insert_statement(record_type: type[Base]):
    return insert(record_type)


def rebuild_route_segments(session: Session) -> RouteSegmentRebuildResult:
    directions = _stored_route_directions(session)
    session.query(RouteSegmentRecord).delete(synchronize_session=False)

    result = RouteSegmentRebuildResult(route_directions=len(directions))
    for route_version_id, route_direction_id, name, geometry in directions:
        direction = RouteDirection(name=name, coordinates=_coordinates_from_linestring_wkt(geometry))
        for segment in materialize_route_segments(direction):
            session.add(
                RouteSegmentRecord(
                    route_version_id=route_version_id,
                    route_direction_id=route_direction_id,
                    sequence=segment.sequence,
                    source_segment_sequence=segment.source_segment_sequence,
                    source_fraction_start=segment.source_fraction_start,
                    source_fraction_end=segment.source_fraction_end,
                    geometry=_segment_linestring_wkt(segment.coordinates),
                    bearing_degrees=segment.bearing_degrees,
                    distance_meters=segment.distance_meters,
                    cumulative_distance_meters=segment.cumulative_distance_meters,
                )
            )
            result.segments_written += 1
    return result


def _stored_route_directions(session: Session) -> list[tuple[PyUUID, PyUUID, str, str]]:
    statement = select(
        RouteDirectionRecord.route_version_id,
        RouteDirectionRecord.id,
        RouteDirectionRecord.name,
        (
            func.ST_AsText(RouteDirectionRecord.geometry)
            if session.get_bind().dialect.name == "postgresql"
            else RouteDirectionRecord.geometry
        ),
    ).order_by(RouteDirectionRecord.route_version_id, RouteDirectionRecord.sequence)
    return [
        (route_version_id, route_direction_id, name, geometry)
        for route_version_id, route_direction_id, name, geometry in session.execute(statement)
    ]


def _linestring_wkt(direction: RouteDirection) -> str:
    return "SRID=4326;LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in direction.coordinates) + ")"


def _segment_linestring_wkt(coordinates: list[tuple[float, float]]) -> str:
    return "SRID=4326;LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in coordinates) + ")"


def _coordinates_from_linestring_wkt(geometry: str) -> list[tuple[float, float]]:
    wkt = geometry.split(";", 1)[-1].strip()
    prefix = "LINESTRING("
    if not wkt.upper().startswith(prefix) or not wkt.endswith(")"):
        raise ValueError(f"unsupported route direction geometry: {geometry}")
    coordinates_text = wkt[len(prefix) : -1]
    coordinates: list[tuple[float, float]] = []
    for coordinate_text in coordinates_text.split(","):
        lon_text, lat_text = coordinate_text.strip().split()[:2]
        coordinates.append((float(lon_text), float(lat_text)))
    return coordinates


def hash_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()

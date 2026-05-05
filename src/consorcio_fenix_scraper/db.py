from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from hashlib import sha256
from uuid import UUID as PyUUID, uuid4

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
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
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
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


def persist_snapshots(session: Session, source_url: str, snapshots: Iterable[RouteSnapshot]) -> ScrapeRunResult:
    run = ScrapeRunRecord(source_url=source_url, status=ScrapeStatus.RUNNING.value)
    session.add(run)
    session.flush()
    logger.info("Created scrape run id=%s source_url=%s", run.id, source_url)

    result = ScrapeRunResult()
    try:
        for snapshot in snapshots:
            version, created = _persist_snapshot(session, run.id, snapshot)
            result.routes += 1
            result.schedules += len(snapshot.route.schedules)
            result.geometries += len(snapshot.directions)
            result.itinerary_steps += len(snapshot.route.itinerary_steps)
            if created:
                _persist_children(session, version.id, snapshot)
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
        run.status = ScrapeStatus.SUCCESS.value
        logger.info("Finished scrape run id=%s status=%s routes=%s", run.id, run.status, result.routes)
    except Exception as exc:
        run.status = ScrapeStatus.FAILED.value
        run.error_summary = str(exc)
        logger.exception("Scrape run id=%s failed: %s", run.id, exc)
        raise
    finally:
        run.finished_at = datetime.now(UTC)
    return result


def _persist_snapshot(session: Session, run_id: PyUUID, snapshot: RouteSnapshot) -> tuple[RouteVersionRecord, bool]:
    route = session.scalar(select(RouteRecord).where(RouteRecord.code == snapshot.route.code))
    if route is None:
        route = RouteRecord(code=snapshot.route.code, name=snapshot.route.name, slug=snapshot.route.slug)
        session.add(route)
        session.flush()

    route.name = snapshot.route.name
    route.slug = snapshot.route.slug
    route.category = snapshot.route.category
    route.fare_region = snapshot.route.fare_region
    route.last_changed = snapshot.route.last_changed
    route.is_current = True
    fare_version = _persist_fare_version(session, snapshot)

    existing_version = session.scalar(
        select(RouteVersionRecord).where(
            RouteVersionRecord.route_id == route.id,
            RouteVersionRecord.source_hash == snapshot.source_hash,
            RouteVersionRecord.map_hash.is_not_distinct_from(snapshot.map_hash),
        )
    )

    session.query(RouteVersionRecord).filter(RouteVersionRecord.route_id == route.id).update({"is_current": False})
    if existing_version is not None:
        existing_version.fare_version_id = fare_version.id if fare_version is not None else None
        existing_version.is_current = True
        session.flush()
        return existing_version, False

    version = RouteVersionRecord(
        route_id=route.id,
        scrape_run_id=run_id,
        fare_version_id=fare_version.id if fare_version is not None else None,
        source_hash=snapshot.source_hash,
        map_hash=snapshot.map_hash,
        page_url=snapshot.route.page_url,
        map_url=snapshot.route.map_url,
        snapshot=snapshot.model_dump(mode="json"),
        is_current=True,
    )
    session.add(version)
    session.flush()
    return version, True


def _persist_fare_version(session: Session, snapshot: RouteSnapshot) -> FareVersionRecord | None:
    fare_policy = snapshot.route.fare_policy
    if fare_policy is None:
        return None

    existing = session.scalar(
        select(FareVersionRecord).where(
            FareVersionRecord.region == fare_policy.region,
            FareVersionRecord.source_hash == _fare_policy_hash(fare_policy),
        )
    )
    if existing is None:
        session.query(FareVersionRecord).filter(FareVersionRecord.region == fare_policy.region).update({"is_current": False})
        existing = FareVersionRecord(
            region=fare_policy.region,
            citizen_card_cents=fare_policy.citizen_card_cents,
            vt_tourist_card_cents=fare_policy.vt_tourist_card_cents,
            cash_qrcode_pix_cents=fare_policy.cash_qrcode_pix_cents,
            source_hash=_fare_policy_hash(fare_policy),
            source_url=snapshot.route.page_url,
            is_current=True,
        )
        session.add(existing)
        session.flush()
        return existing

    session.query(FareVersionRecord).filter(
        FareVersionRecord.region == fare_policy.region,
        FareVersionRecord.id != existing.id,
    ).update({"is_current": False})
    existing.is_current = True
    session.flush()
    return existing


def _fare_policy_hash(fare_policy: FarePolicy) -> str:
    payload = json.dumps(fare_policy.model_dump(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def _persist_children(session: Session, route_version_id: PyUUID, snapshot: RouteSnapshot) -> None:
    route_directions: list[RouteDirectionRecord] = []
    direction_by_sequence: dict[int, RouteDirection] = {}
    for index, direction in enumerate(snapshot.directions, start=1):
        route_direction = RouteDirectionRecord(
            route_version_id=route_version_id,
            name=direction.name,
            sequence=index,
            geometry=_linestring_wkt(direction),
        )
        session.add(route_direction)
        route_directions.append(route_direction)
        direction_by_sequence[index] = direction
    session.flush()

    for route_direction in route_directions:
        direction = direction_by_sequence[route_direction.sequence]
        for segment in materialize_route_segments(direction):
            session.add(
                RouteSegmentRecord(
                    route_version_id=route_version_id,
                    route_direction_id=route_direction.id,
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

    route_direction_by_sequence = {direction.sequence: direction.id for direction in route_directions}
    matches_by_service_sequence = {match.service_direction_sequence: match for match in snapshot.direction_matches}
    service_directions: list[ServiceDirectionRecord] = []
    for service_direction in sorted(snapshot.route.service_directions, key=lambda service: service.sequence):
        match = matches_by_service_sequence.get(service_direction.sequence)
        route_direction_id = (
            route_direction_by_sequence.get(match.route_direction_sequence)
            if match is not None and match.route_direction_sequence is not None
            else None
        )
        service_record = ServiceDirectionRecord(
            route_version_id=route_version_id,
            route_direction_id=route_direction_id,
            sequence=service_direction.sequence,
            departure_label=service_direction.departure_label,
            normalized_name=service_direction.normalized_name,
            direction_kind=service_direction.direction_kind,
            confidence=(match.confidence.value if match is not None else DirectionMatchConfidence.NONE.value),
            method=(match.method.value if match is not None else DirectionMatchMethod.UNMATCHED.value),
            notes=dict(match.notes) if match is not None else {},
        )
        session.add(service_record)
        service_directions.append(service_record)
    session.flush()

    service_direction_by_sequence = {direction.sequence: direction.id for direction in service_directions}
    for service_direction in snapshot.route.service_directions:
        service_direction_id = service_direction_by_sequence[service_direction.sequence]
        for entry in service_direction.schedules:
            session.add(
                ScheduleEntryRecord(
                    route_version_id=route_version_id,
                    service_direction_id=service_direction_id,
                    day_type=entry.day_type,
                    departure_label=entry.departure_label,
                    time=entry.time,
                    flags=list(entry.flags),
                )
            )
    for step in snapshot.route.itinerary_steps:
        session.add(ItineraryStepRecord(route_version_id=route_version_id, sequence=step.sequence, name=step.name))


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

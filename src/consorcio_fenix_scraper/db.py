from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime
from hashlib import sha256

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from consorcio_fenix_scraper.domain import RouteDirection, RouteSnapshot, ScrapeRunResult, ScrapeStatus


class Base(DeclarativeBase):
    pass


class ScrapeRunRecord(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_url: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default=ScrapeStatus.RUNNING.value)
    error_summary: Mapped[str | None] = mapped_column(Text)


class RouteRecord(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    fare_cents: Mapped[int | None] = mapped_column(Integer)
    last_changed: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)

    versions: Mapped[list["RouteVersionRecord"]] = relationship(back_populates="route")


class RouteVersionRecord(Base):
    __tablename__ = "route_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"), index=True)
    scrape_run_id: Mapped[int] = mapped_column(ForeignKey("scrape_runs.id"), index=True)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    map_hash: Mapped[str | None] = mapped_column(String(64))
    page_url: Mapped[str] = mapped_column(Text)
    map_url: Mapped[str | None] = mapped_column(Text)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    route: Mapped[RouteRecord] = relationship(back_populates="versions")


class RouteDirectionRecord(Base):
    __tablename__ = "route_directions"

    id: Mapped[int] = mapped_column(primary_key=True)
    route_version_id: Mapped[int] = mapped_column(ForeignKey("route_versions.id"), index=True)
    name: Mapped[str] = mapped_column(Text)
    sequence: Mapped[int] = mapped_column(Integer)
    geometry: Mapped[object] = mapped_column(Geometry("LINESTRING", srid=4326))


class ScheduleEntryRecord(Base):
    __tablename__ = "schedule_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    route_version_id: Mapped[int] = mapped_column(ForeignKey("route_versions.id"), index=True)
    day_type: Mapped[str] = mapped_column(Text)
    departure_label: Mapped[str] = mapped_column(Text)
    time: Mapped[str] = mapped_column(String(5))
    flags: Mapped[list[str]] = mapped_column(JSONB, default=list)


class ItineraryStepRecord(Base):
    __tablename__ = "itinerary_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    route_version_id: Mapped[int] = mapped_column(ForeignKey("route_versions.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)


class StopRecord(Base):
    __tablename__ = "stops"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str | None] = mapped_column(Text, index=True)
    name: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    geometry: Mapped[object | None] = mapped_column(Geometry("POINT", srid=4326))


class RawPageRecord(Base):
    __tablename__ = "raw_pages"
    __table_args__ = (UniqueConstraint("scrape_run_id", "url", name="uq_raw_page_run_url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scrape_run_id: Mapped[int] = mapped_column(ForeignKey("scrape_runs.id"), index=True)
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

    result = ScrapeRunResult()
    try:
        for snapshot in snapshots:
            version = _persist_snapshot(session, run.id, snapshot)
            result.routes += 1
            result.schedules += len(snapshot.route.schedules)
            result.geometries += len(snapshot.directions)
            result.itinerary_steps += len(snapshot.route.itinerary_steps)
            _persist_children(session, version.id, snapshot)
        run.status = ScrapeStatus.SUCCESS.value
    except Exception as exc:
        run.status = ScrapeStatus.FAILED.value
        run.error_summary = str(exc)
        raise
    finally:
        run.finished_at = datetime.now(UTC)
    return result


def _persist_snapshot(session: Session, run_id: int, snapshot: RouteSnapshot) -> RouteVersionRecord:
    route = session.scalar(select(RouteRecord).where(RouteRecord.code == snapshot.route.code))
    if route is None:
        route = RouteRecord(code=snapshot.route.code, name=snapshot.route.name, slug=snapshot.route.slug)
        session.add(route)
        session.flush()

    route.name = snapshot.route.name
    route.slug = snapshot.route.slug
    route.category = snapshot.route.category
    route.fare_cents = snapshot.route.fare_cents
    route.last_changed = snapshot.route.last_changed
    route.is_current = True

    session.query(RouteVersionRecord).filter(RouteVersionRecord.route_id == route.id).update({"is_current": False})
    version = RouteVersionRecord(
        route_id=route.id,
        scrape_run_id=run_id,
        source_hash=snapshot.source_hash,
        map_hash=snapshot.map_hash,
        page_url=snapshot.route.page_url,
        map_url=snapshot.route.map_url,
        snapshot=snapshot.model_dump(mode="json"),
        is_current=True,
    )
    session.add(version)
    session.flush()
    return version


def _persist_children(session: Session, route_version_id: int, snapshot: RouteSnapshot) -> None:
    for index, direction in enumerate(snapshot.directions, start=1):
        session.add(
            RouteDirectionRecord(
                route_version_id=route_version_id,
                name=direction.name,
                sequence=index,
                geometry=_linestring_wkt(direction),
            )
        )
    for entry in snapshot.route.schedules:
        session.add(
            ScheduleEntryRecord(
                route_version_id=route_version_id,
                day_type=entry.day_type,
                departure_label=entry.departure_label,
                time=entry.time,
                flags=list(entry.flags),
            )
        )
    for step in snapshot.route.itinerary_steps:
        session.add(ItineraryStepRecord(route_version_id=route_version_id, sequence=step.sequence, name=step.name))


def _linestring_wkt(direction: RouteDirection) -> str:
    return "SRID=4326;LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in direction.coordinates) + ")"


def hash_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()

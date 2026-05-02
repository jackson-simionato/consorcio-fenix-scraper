from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class ScrapeStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class ScheduleFlag(StrEnum):
    ACCESSIBLE = "E"
    PREDICTED = "*"
    HALF_TRIP = "M"
    RETURN_TO_GARAGE = "R"


class ScheduleEntry(BaseModel):
    day_type: str
    departure_label: str
    time: str
    flags: tuple[str, ...] = Field(default_factory=tuple)


class ItineraryStep(BaseModel):
    sequence: int
    name: str


class RouteDirection(BaseModel):
    name: str
    coordinates: list[tuple[float, float]]
    geometry_type: Literal["LineString"] = "LineString"


class ParsedRoutePage(BaseModel):
    code: str
    name: str
    slug: str
    page_url: str
    map_url: str | None = None
    category: str | None = None
    fare_cents: int | None = None
    last_changed: date | None = None
    schedules: list[ScheduleEntry] = Field(default_factory=list)
    itinerary_steps: list[ItineraryStep] = Field(default_factory=list)


class RouteSnapshot(BaseModel):
    route: ParsedRoutePage
    directions: list[RouteDirection] = Field(default_factory=list)
    source_hash: str
    map_hash: str | None = None


class ScrapeRunResult(BaseModel):
    routes: int = 0
    schedules: int = 0
    geometries: int = 0
    itinerary_steps: int = 0
    stops: int = 0
    warnings: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)


class ScrapeRun(BaseModel):
    id: UUID | None = None
    source_url: HttpUrl | str
    started_at: datetime
    finished_at: datetime | None = None
    status: ScrapeStatus = ScrapeStatus.RUNNING
    error_summary: str | None = None

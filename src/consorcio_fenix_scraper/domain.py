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


class ItineraryStep(BaseModel):
    sequence: int
    name: str


class RouteDirection(BaseModel):
    name: str
    coordinates: list[tuple[float, float]]
    geometry_type: Literal["LineString"] = "LineString"


class MaterializedRouteSegment(BaseModel):
    sequence: int
    source_segment_sequence: int
    source_fraction_start: float
    source_fraction_end: float
    coordinates: list[tuple[float, float]]
    bearing_degrees: float
    distance_meters: float
    cumulative_distance_meters: float


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


class FarePolicy(BaseModel):
    region: str
    citizen_card_cents: int | None = None
    vt_tourist_card_cents: int | None = None
    cash_qrcode_pix_cents: int | None = None


class ParsedRoutePage(BaseModel):
    code: str
    name: str
    slug: str
    page_url: str
    map_url: str | None = None
    category: str | None = None
    fare_region: str | None = None
    fare_policy: FarePolicy | None = None
    last_changed: date | None = None
    service_directions: list[ServiceDirection] = Field(default_factory=list)
    schedules: list[ScheduleEntry] = Field(default_factory=list)
    itinerary_steps: list[ItineraryStep] = Field(default_factory=list)


class RouteSnapshot(BaseModel):
    route: ParsedRoutePage
    directions: list[RouteDirection] = Field(default_factory=list)
    direction_matches: list[ServiceDirectionMatch] = Field(default_factory=list)
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

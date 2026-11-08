from datetime import date as Date
from datetime import datetime
from typing import Annotated, Generic, Literal, Self, TypeVar
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveFloat,
    PositiveInt,
    model_validator,
)

Text = Annotated[str, Field(min_length=1)]
Mode = Literal["mock", "real"]
T = TypeVar("T")


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ToolError(Contract):
    code: Text
    message: Text
    retryable: bool = False


class ToolResult(Contract, Generic[T]):
    status: Literal["success", "error", "degraded"]
    data: T | None = None
    source: Text
    mode: Mode
    error: ToolError | None = None

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.status == "error" and self.error is None:
            raise ValueError("An error result requires a typed error")
        if self.status != "error" and self.data is None:
            raise ValueError("Expected result data")
        return self


class TripResult(Contract):
    request_id: UUID
    status: Literal["confirmed", "failed"]
    route_id: Text | None = None
    date: Date | None = None
    guide_id: Text | None = None
    reservation_id: Text | None = None
    equipment_items: list[Text] = Field(default_factory=list)
    failure_reason: Text | None = None

    @model_validator(mode="after")
    def check_terminal(self) -> Self:
        if self.status == "confirmed" and not all(
            (self.route_id, self.date, self.guide_id, self.reservation_id)
        ):
            raise ValueError(
                "Confirmed trips require route, date, guide and reservation"
            )
        if self.status == "failed" and not self.failure_reason:
            raise ValueError("Failed trips require a reason")
        return self


class Proposal(Contract):
    route_id: Text
    date: Date
    guide_id: Text
    equipment: dict[Text, PositiveInt] = Field(default_factory=dict)


class BookingRequest(Proposal):
    request_id: UUID
    idempotency_key: Text
    approval_ref: Text


class Reservation(Proposal):
    reservation_id: Text
    status: Literal["confirmed"]
    created_at: datetime


class WeatherQuery(Contract):
    location: Text
    date: Date
    end_date: Date | None = None


class ForecastDay(Contract):
    date: Date
    temperature_c: float
    precipitation_probability: Annotated[int, Field(ge=0, le=100)]
    precipitation_mm: Annotated[float, Field(ge=0)]
    wind_kmh: Annotated[float, Field(ge=0)]


class Forecast(Contract):
    location: Text
    days: list[ForecastDay]
    issued_at: datetime
    provider: Text


class RouteQuery(Contract):
    location: Text
    difficulty: Text
    max_hours: PositiveFloat
    max_km: PositiveFloat | None = None
    max_gain_m: int | None = None


class RouteLookup(Contract):
    route_id: Text


class RouteSummary(RouteLookup):
    name: Text
    difficulty: Text
    distance_km: PositiveFloat
    duration_hours: PositiveFloat
    elevation_gain_m: int


class RouteDetails(RouteSummary):
    description: Text
    constraints: list[str]
    source: Text


class GearQuery(Contract):
    route: RouteSummary
    weather: ForecastDay
    duration_hours: PositiveFloat
    owned: list[str] = Field(default_factory=list)


class GearAdvice(Contract):
    required: list[str]
    recommended: list[str]
    missing: list[str]
    reasons: dict[str, str]


class GuideQuery(RouteLookup):
    date: Date
    group_size: PositiveInt = 1


class Guide(Contract):
    guide_id: Text
    name: Text
    available: bool
    qualifications: list[str]


class InventoryQuery(Contract):
    date: Date
    items: dict[Text, PositiveInt]


class Inventory(Contract):
    quantities: dict[str, Annotated[int, Field(ge=0)]]
    unavailable: list[str]

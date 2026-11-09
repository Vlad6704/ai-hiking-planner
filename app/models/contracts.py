from datetime import date as Date
from datetime import datetime
from typing import Annotated, Generic, Literal, Self, TypeVar
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PositiveFloat,
    PositiveInt,
    model_validator,
)

Text = Annotated[str, Field(min_length=1)]
Mode = Literal["mock", "real"]


def item_name(value):
    if not isinstance(value, str):
        return value
    name = " ".join(value.replace("_", " ").replace("-", " ").casefold().split())
    return {"waterproof poncho": "poncho", "rain poncho": "poncho",
            "rain jackets": "rain jacket", "ponchos": "poncho"}.get(name, name)


ItemName = Annotated[Text, BeforeValidator(item_name)]
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
    metadata: dict | None = None

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
    equipment_items: list[ItemName] = Field(default_factory=list)
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
    equipment: dict[ItemName, PositiveInt] = Field(default_factory=dict)


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
    issued_at: AwareDatetime
    provider: Text


class RouteQuery(Contract):
    location: Text | None = None
    difficulty: Text | None = None
    min_hours: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    max_hours: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None = None
    min_km: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    max_km: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None = None
    min_gain_m: Annotated[int, Field(ge=0)] | None = None
    max_gain_m: Annotated[int, Field(ge=0)] | None = None
    min_loss_m: Annotated[int, Field(ge=0)] | None = None
    max_loss_m: Annotated[int, Field(ge=0)] | None = None
    keywords: list[str] | None = Field(default=None, max_length=20)
    keyword_match: Literal["all", "any"] | None = "all"
    prefix: bool | None = False
    sort: Literal["relevance", "name", "distance", "duration", "ascent", "descent"] | None = None
    limit: Annotated[int, Field(ge=1, le=100)] | None = 20
    offset: Annotated[int, Field(ge=0)] | None = 0

    @model_validator(mode="after")
    def validate_search(self):
        for low, high in (("min_hours", "max_hours"), ("min_km", "max_km"),
                          ("min_gain_m", "max_gain_m"), ("min_loss_m", "max_loss_m")):
            if getattr(self, low) is not None and getattr(self, high) is not None and getattr(self, low) > getattr(self, high):
                raise ValueError(f"{low} must not exceed {high}")
        self.keywords = [word.strip() for word in (self.keywords or []) if word.strip()]
        if any(len(word) > 100 for word in self.keywords) or sum(map(len, self.keywords)) > 1000:
            raise ValueError("keyword_query_too_long")
        self.limit = 20 if self.limit is None else self.limit
        self.offset = 0 if self.offset is None else self.offset
        self.keyword_match = self.keyword_match or "all"
        self.prefix = bool(self.prefix)
        return self


class RouteLookup(Contract):
    route_id: Text


class RouteSummary(RouteLookup):
    name: Text
    difficulty: Text
    distance_km: PositiveFloat | None = None
    duration_hours: PositiveFloat | None = None
    elevation_gain_m: int | None = None


class RouteDetails(RouteSummary):
    description: Text
    constraints: list[str]
    source: Text
    source_route_id: str | None = None
    variant_id: str | None = None
    elevation_loss_m: int | None = None
    layout: str | None = None
    source_language: str | None = None
    content_hash: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    last_checked_at: str | None = None
    snippet: str | None = None
    catalog_stale: bool = False
    catalog_run_id: str | None = None


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
    items: dict[ItemName, PositiveInt]


class Inventory(Contract):
    quantities: dict[str, Annotated[int, Field(ge=0)]]
    unavailable: list[str]

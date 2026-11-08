import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from app.models.contracts import (
    Forecast,
    ForecastDay,
    GearAdvice,
    GearQuery,
    RouteDetails,
    RouteQuery,
    WeatherQuery,
)

ROOT = Path(__file__).resolve().parents[2]


def catalog(name):
    return json.loads((ROOT / "catalogs" / f"{name}.json").read_text(encoding="utf-8"))


def search(q: RouteQuery):
    routes = [RouteDetails(**r) for r in catalog("routes")]
    return [
        r
        for r in routes
        if q.location.lower() == "picos de europa"
        and r.difficulty == q.difficulty
        and r.duration_hours <= q.max_hours
        and (q.max_km is None or r.distance_km <= q.max_km)
        and (q.max_gain_m is None or r.elevation_gain_m <= q.max_gain_m)
    ]


def details(route_id):
    for row in catalog("routes"):
        if row["route_id"] == route_id:
            return RouteDetails(**row)
    raise ValueError("route_not_found")


def gear(q: GearQuery):
    kit = catalog("equipment")
    required = kit["day"] + (kit["overnight"] if q.duration_hours >= 24 else [])
    if q.weather.temperature_c < 8:
        required.append("warm layer")
    return GearAdvice(
        required=required,
        recommended=kit["recommended"],
        missing=[i for i in required if i not in q.owned],
        reasons={
            i: "Overnight equipment"
            if i in kit["overnight"]
            else "Trail and weather protection"
            for i in required
        },
    )


def select_forecast(forecast: Forecast, q: WeatherQuery):
    end = q.end_date or q.date
    days = [d for d in forecast.days if q.date <= d.date <= end]
    if (
        forecast.location.lower() != q.location.lower()
        or end < q.date
        or len({d.date for d in days}) != (end - q.date).days + 1
    ):
        raise ValueError("unsupported_forecast")
    return forecast.model_copy(update={"days": days})


def fallback_weather(forecast, q, now, hours):
    if (
        forecast.provider != "approved_snapshot"
        or not timedelta() <= now - forecast.issued_at <= timedelta(hours=hours)
    ):
        raise ValueError("ineligible_fallback")
    return select_forecast(forecast, q)


async def live_weather(client: httpx.AsyncClient, q: WeatherQuery):
    if q.location.lower() != "picos de europa":
        raise ValueError("invalid_location")
    fields = [
        "temperature_2m_max",
        "precipitation_probability_max",
        "precipitation_sum",
        "wind_speed_10m_max",
    ]
    response = await client.get(
        "https://api.open-meteo.com/v1/forecast",
        params=dict(
            latitude=43.27,
            longitude=-4.99,
            daily=",".join(fields),
            start_date=str(q.date),
            end_date=str(q.end_date or q.date),
        ),
    )
    response.raise_for_status()
    daily = response.json()["daily"]
    days = [
        ForecastDay(
            date=date,
            temperature_c=daily[fields[0]][i],
            precipitation_probability=daily[fields[1]][i],
            precipitation_mm=daily[fields[2]][i],
            wind_kmh=daily[fields[3]][i],
        )
        for i, date in enumerate(daily["time"])
    ]
    return select_forecast(
        Forecast(
            location=q.location,
            days=days,
            provider="Open-Meteo",
            issued_at=datetime.now(UTC),
        ),
        q,
    )

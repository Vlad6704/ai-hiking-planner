import json
import math
import re
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
    if q.location and q.location.casefold() != "picos de europa":
        return []
    selected = []
    for route in routes:
        if q.difficulty and route.difficulty != q.difficulty.casefold():
            continue
        bounds = (("hours", route.duration_hours), ("km", route.distance_km),
                  ("gain_m", route.elevation_gain_m), ("loss_m", route.elevation_loss_m))
        if any((getattr(q, "min_" + field) is not None and (value is None or value < getattr(q, "min_" + field)))
               or (getattr(q, "max_" + field) is not None and (value is None or value > getattr(q, "max_" + field)))
               for field, value in bounds):
            continue
        text = (route.name + " " + route.description + " " + " ".join(route.constraints)).casefold()
        matches = [bool(re.search(r"\b" + re.escape(word.casefold()) + (r"\w*\b" if q.prefix else r"\b"), text)) for word in q.keywords]
        if matches and not (all(matches) if q.keyword_match == "all" else any(matches)):
            continue
        selected.append(route)
    fields = {"name": "name", "distance": "distance_km", "duration": "duration_hours", "ascent": "elevation_gain_m", "descent": "elevation_loss_m"}
    if q.sort in fields:
        field = fields[q.sort]
        selected.sort(key=lambda route: (getattr(route, field) is None, getattr(route, field), route.route_id))
    else:
        selected.sort(key=lambda route: route.route_id)
    return selected[q.offset:q.offset + q.limit]


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
    end = q.end_date or q.date
    if end < q.date or (end - q.date).days >= 16:
        raise ValueError("unsupported_forecast")
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
            timezone="Europe/Madrid",
            temperature_unit="celsius",
            wind_speed_unit="kmh",
            precipitation_unit="mm",
        ),
    )
    response.raise_for_status()
    try:
        document = response.json()
        daily = document["daily"]
        units = document["daily_units"]
        expected_units = ["°C", "%", "mm", "km/h"]
        times = daily["time"]
        if not isinstance(times, list) or not times or len(set(times)) != len(times):
            raise ValueError()
        for field, unit in zip(fields, expected_units):
            values = daily[field]
            if units[field] != unit or not isinstance(values, list) or len(values) != len(times):
                raise ValueError()
            if any(isinstance(value, bool) or value is None or not math.isfinite(float(value)) for value in values):
                raise ValueError()
        days = [ForecastDay(date=day, temperature_c=daily[fields[0]][i],
                            precipitation_probability=daily[fields[1]][i],
                            precipitation_mm=daily[fields[2]][i], wind_kmh=daily[fields[3]][i])
                for i, day in enumerate(times)]
        forecast = select_forecast(
            Forecast(
                location=q.location,
                days=days,
                provider="Open-Meteo",
                issued_at=datetime.now(UTC),
            ),
            q,
        )
    except (KeyError, TypeError, ValueError, IndexError, OverflowError) as exc:
        raise ValueError("invalid_weather_response") from exc
    return forecast

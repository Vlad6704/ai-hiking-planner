import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from app.models.contracts import (
    Forecast,
    ForecastDay,
    GearAdvice,
    GearQuery,
    WeatherQuery,
)

ROOT = Path(__file__).resolve().parents[2]


def catalog(name):
    return json.loads((ROOT / "catalogs" / f"{name}.json").read_text(encoding="utf-8"))


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


def mock_forecast(forecast: Forecast, q: WeatherQuery):
    aliases = {"picos de europa", "lagos de covadonga", "picos de europa, lagos de covadonga"}
    if forecast.location.casefold() == "picos de europa" and q.location.strip().casefold() in aliases:
        q = q.model_copy(update={"location": forecast.location})
    return select_forecast(forecast, q)


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

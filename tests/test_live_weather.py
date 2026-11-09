import asyncio
from datetime import date

import httpx
import pytest

from app.models.contracts import WeatherQuery
from app.tools.planning import live_weather


def payload():
    return {
        "daily_units": {"time": "iso8601", "temperature_2m_max": "°C",
                        "precipitation_probability_max": "%", "precipitation_sum": "mm",
                        "wind_speed_10m_max": "km/h"},
        "daily": {"time": ["2026-11-10"], "temperature_2m_max": [12.5],
                  "precipitation_probability_max": [20], "precipitation_sum": [1.2],
                  "wind_speed_10m_max": [15.0]},
    }


def test_live_weather_requests_explicit_units_and_timezone():
    def respond(request):
        assert request.url.host == "api.open-meteo.com"
        assert request.url.params["timezone"] == "Europe/Madrid"
        assert request.url.params["temperature_unit"] == "celsius"
        assert request.url.params["wind_speed_unit"] == "kmh"
        assert request.url.params["precipitation_unit"] == "mm"
        return httpx.Response(200, json=payload())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result = await live_weather(client, WeatherQuery(location="Picos de Europa", date="2026-11-10"))
            assert result.provider == "Open-Meteo"
            assert result.days[0].date == date(2026, 11, 10)
            assert result.days[0].wind_kmh == 15
    asyncio.run(run())


@pytest.mark.parametrize("change", ["missing", "length", "null", "unit", "nonfinite"])
def test_malformed_weather_is_a_typed_value_error(change):
    data = payload()
    if change == "missing":
        del data["daily"]["temperature_2m_max"]
    elif change == "length":
        data["daily"]["wind_speed_10m_max"] = []
    elif change == "null":
        data["daily"]["temperature_2m_max"] = [None]
    elif change == "unit":
        data["daily_units"]["wind_speed_10m_max"] = "mph"
    else:
        data["daily"]["temperature_2m_max"] = [float("inf")]

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))) as client:
            with pytest.raises(ValueError, match="invalid_weather_response"):
                await live_weather(client, WeatherQuery(location="Picos de Europa", date="2026-11-10"))
    if change == "nonfinite":
        data["daily"]["temperature_2m_max"] = ["Infinity"]
    asyncio.run(run())


def test_invalid_date_range_does_not_call_provider():
    async def run():
        def respond(_):
            pytest.fail("Invalid date range must be rejected before HTTP")
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(ValueError, match="unsupported_forecast"):
                await live_weather(client, WeatherQuery(location="Picos de Europa", date="2026-11-11", end_date="2026-11-10"))
    asyncio.run(run())


def test_manual_cli_forwards_real_environment(monkeypatch):
    import sys
    from app.simulation import manual
    seen = []
    monkeypatch.setattr(manual, "launch", lambda **kwargs: seen.append(kwargs) or 0)
    monkeypatch.setattr(sys, "argv", ["manual", "--mode", "real"])
    assert manual.main() == 0
    assert seen[0]["mode"] == "real"

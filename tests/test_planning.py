import asyncio
import pytest

from app.models.contracts import RouteQuery
from app.observability.trace import TraceRecorder
from app.simulation.config import Settings
from app.tools.execution import execute
from app.route_catalog.seed import seed_store
from app.route_catalog.store import CatalogStore


@pytest.mark.parametrize("location", [
    "Picos de Europa", "Lagos de Covadonga", "Picos de Europa, Lagos de Covadonga",
    "Lagos de Covadonga, Picos de Europa", "Picos de Europa, Asturias, Spain",
    "Lagos de Covadonga, Asturias, Spain", "Lagos de Covadonga, Picos de Europa, Asturias, Spain",
    "  LAGOS  DE COVADONGA ,  PICOS DE EUROPA  ",
])
def test_mock_forecast_accepts_known_location_names(location):
    from app.models.contracts import Forecast, WeatherQuery
    from app.simulation.scenario import load_scenario
    from app.tools.planning import mock_forecast
    forecast = Forecast.model_validate(load_scenario("bad_weather")["weather"])
    result = mock_forecast(forecast, WeatherQuery(location=location, date="2026-11-10"))
    assert result.days[0].wind_kmh == 75
    with pytest.raises(ValueError, match="unsupported_forecast"):
        mock_forecast(forecast, WeatherQuery(location="Madrid", date="2026-11-10"))
    with pytest.raises(ValueError, match="unsupported_forecast"):
        mock_forecast(forecast, WeatherQuery(location=location, date="2027-01-01"))


@pytest.mark.parametrize('location', ['Asturias, Spain', 'Madrid, Picos de Europa',
                                     'Not Picos de Europa', 'Lagos de Covadonga, Madrid'])
def test_mock_location_normalization_does_not_accept_unknown_or_ambiguous_places(location):
    from app.models.contracts import Forecast, WeatherQuery
    from app.simulation.scenario import load_scenario
    from app.tools.planning import mock_forecast
    forecast = Forecast.model_validate(load_scenario('happy_path')['weather'])
    with pytest.raises(ValueError, match='unsupported_forecast'):
        mock_forecast(forecast, WeatherQuery(location=location, date='2026-11-10'))


def test_mock_alias_date_range_preserves_input_and_snapshot_location():
    from app.models.contracts import Forecast, WeatherQuery
    from app.simulation.scenario import load_scenario
    from app.tools.planning import mock_forecast
    forecast = Forecast.model_validate(load_scenario('happy_path')['weather'])
    query = WeatherQuery(location='Lagos de Covadonga, Picos de Europa',
                         date='2026-11-10', end_date='2026-11-11')
    result = mock_forecast(forecast, query)
    assert result.location == 'Picos de Europa' and len(result.days) == 2
    assert query.location == 'Lagos de Covadonga, Picos de Europa'
    assert forecast.model_dump() == Forecast.model_validate(load_scenario('happy_path')['weather']).model_dump()


def test_baseline_customer_can_answer_structured_offer():
    from app.humans.simulator import HumanSimulator
    from app.simulation.scenario import load_scenario
    human = HumanSimulator(load_scenario("happy_path")["rules"])
    reply = human.answer("Do you accept these exact terms?", intent="substitution")
    assert reply["matched_intent"] == ["substitution"]
    assert reply["text"] == "Yes, I accept the proposed guided hike and rental equipment."


def test_route_and_gear_rules(tmp_path):
    store = CatalogStore(tmp_path / 'routes.sqlite3')
    seed_store(store, checked_at='2026-11-08T12:00:00+00:00')
    q = RouteQuery(location="Picos de Europa", difficulty="easy", max_hours=4, keywords=['Enol'])
    assert 'PR-PNPE-2:long' in {row['route_id'] for row in store.search(q)}
    assert store.details("PR-PNPE-2:long")['elevation_gain_m'] == 50
    assert store.search(q.model_copy(update={"max_km": 2})) == []


def test_retry_schedule():
    calls = []

    async def call():
        calls.append(1)
        raise TimeoutError()

    trace = TraceRecorder({})
    result = asyncio.run(
        execute(
            "weather",
            {},
            call,
            Settings(),
            trace,
            "agent_a",
            fallback=lambda: {"ok": True},
        )
    )
    assert result["status"] == "degraded" and len(calls) == 3

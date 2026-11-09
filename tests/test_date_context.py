import asyncio
import re
from datetime import UTC, date, datetime

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from app.agents.factory import build_agent
from app.simulation.config import Settings
from app.simulation.runner import SimulationRunner
from app.simulation.scenario import load_scenario


class DateContextModel(BaseChatModel):
    seen: list[str] = Field(default_factory=list)
    finish: bool = False

    @property
    def _llm_type(self):
        return 'date-context-test'

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages[0].content)
        message = AIMessage(content='Date context received.')
        if self.finish:
            rid = re.search(r'Request ID ([\w-]+)', messages[1].content).group(1)
            message = AIMessage(content='', tool_calls=[dict(name='submit_trip_result', id='finish', args=dict(
                result=dict(request_id=rid, status='failed', failure_reason='Test completed'),
                final_message='Test completed'))])
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.mark.parametrize('actor', ['agent_a', 'agent_b'])
def test_local_date_reaches_the_model_system_message(actor):
    model = DateContextModel()
    agent = build_agent(actor, [], model, InMemorySaver(), current_date=date(2030, 11, 9))
    agent.invoke({'messages': [('user', '10-12 nov, about three hours')], 'request_id': 'test'},
                 {'configurable': {'thread_id': actor}})
    assert '2030-11-09' in model.seen[0]
    assert 'Europe/Warsaw' in model.seen[0]


def test_mock_date_uses_scenario_clock_across_year_boundary():
    case = load_scenario('happy_path')
    case['clock'] = '2026-12-31T23:30:00+00:00'
    run = SimulationRunner(case, Settings(), 42)
    assert run.current_date == date(2027, 1, 1)
    assert run.trace.metadata['current_date'] == '2027-01-01'
    assert run.trace.metadata['timezone'] == 'Europe/Warsaw'


def test_real_scenario_and_runner_share_warsaw_date(monkeypatch, tmp_path):
    import app.time_context as time_context

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2030, 12, 31, 23, 30, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(time_context, 'datetime', FixedDateTime)
    monkeypatch.setenv('OPERATOR_URL', 'http://127.0.0.1:8765')
    monkeypatch.setenv('ROUTE_CATALOG_DB', str(tmp_path / 'routes.sqlite3'))
    case = load_scenario('happy_path', mode='real')
    assert '2031-01-02' in case['initial']
    model = DateContextModel(finish=True)
    run = SimulationRunner(case, Settings(mode='real'), 42, model)
    asyncio.run(run.run())
    assert run.error is None
    assert run.current_date == date(2031, 1, 1)
    assert run.trace.metadata['current_date'] == '2031-01-01'
    assert '2031-01-01' in model.seen[0]
    assert 'Europe/Warsaw' in model.seen[0]

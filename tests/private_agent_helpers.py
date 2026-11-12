"""Explicit private-state setup for focused tool tests."""

from contextlib import contextmanager
from uuid import uuid4

from app.agents.context import AgentContext
from app.observability.trace import TraceRecorder
from app.simulation.config import Settings
from app.simulation.scenario import load_scenario
from app.tools.adapters.mock import FailureSchedule
from app.tools.operator import MockOperator


def make_context(actor='agent_a', **resources):
    if actor == 'agent_b':
        resources.setdefault('provider', MockOperator({}, {}, []))
    return AgentContext(actor, str(uuid4()), Settings(), load_scenario('happy_path'),
                        TraceRecorder({}), injection=FailureSchedule({}, 42), **resources)


@contextmanager
def scoped(context, state):
    with context.activate(state) as working:
        working.setdefault('_tool_call_id', str(uuid4()))
        yield working
        for key, value in context.changes(state, working).items():
            if key in {'observations', 'inbox', 'outbox', 'interactions', 'planning_facts', 'dispatch_ack'}:
                state.setdefault(key, {}).update(value)
            else:
                state[key] = value

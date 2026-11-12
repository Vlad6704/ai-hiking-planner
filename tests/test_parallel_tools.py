import asyncio
import json
from collections import Counter

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.factory import build_agent
from app.agents.tools import bind_tools
from app.simulation.config import Settings
from app.simulation.runner import SimulationRunner
from app.simulation.scenario import load_scenario


class BatchModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "parallel-tools-regression"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        results = [message for message in messages if isinstance(message, ToolMessage)]
        if not results:
            calls = [
                dict(name="check_guide_availability", id="guides",
                     args=dict(route_id="PR-PNPE-2:long", date="2026-11-10")),
                dict(name="check_equipment_inventory", id="stock",
                     args=dict(date="2026-11-10", items={"rain jacket": 1})),
            ]
            message = AIMessage(content="", tool_calls=calls)
        elif len(results) == 2:
            message = AIMessage(content="", tool_calls=[
                dict(name="ask_human", id="question", args=dict(question="Continue?"))
            ])
        else:
            message = AIMessage(content="Complete")
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.mark.parametrize("inventory_fails", [False, True])
def test_parallel_reads_complete_before_human_interrupt_and_are_not_replayed(inventory_fails):
    async def run():
        started = set()
        both_started = asyncio.Event()
        calls = Counter()

        async def rendezvous(name):
            calls[name] += 1
            started.add(name)
            if len(started) == 2:
                both_started.set()
            await both_started.wait()

        class Provider:
            async def guides(self, query):
                await rendezvous("guides")
                return []

            async def inventory(self, query):
                await rendezvous("stock")
                if inventory_fails:
                    raise ValueError("inventory_unavailable")
                return dict(quantities={"rain jacket": 3}, unavailable=[])

        trip = SimulationRunner(load_scenario("happy_path"), Settings(), 42)
        from private_agent_helpers import make_context
        context = make_context('agent_b', provider=Provider())
        graph = build_agent('agent_b', bind_tools('agent_b', context), BatchModel(), InMemorySaver(), agent_context=context)
        config = {"configurable": {"thread_id": "parallel-regression"}}
        async with asyncio.timeout(5):
            state = await graph.ainvoke({"messages": [("user", "Check both")],
                                        "request_id": trip.rid}, config)
            while not state.get('__interrupt__'):
                assert (await graph.aget_state(config)).next
                state = await graph.ainvoke(None, config)
            assert len(state['__interrupt__']) == 1
            results = {message.tool_call_id: json.loads(message.content)
                       for message in state["messages"] if isinstance(message, ToolMessage)}
            assert results["guides"]["status"] == "success"
            assert results["stock"]["status"] == ("error" if inventory_fails else "success")
            resumed = await graph.ainvoke(Command(resume={
                state['__interrupt__'][0].id: {'text': 'Yes', 'matched_intent': ['manual'], 'interaction_id': 'parallel-question'}
            }), config)
            while (await graph.aget_state(config)).next:
                resumed = await graph.ainvoke(None, config)
        assert resumed['messages'][-1].content == 'Complete'
        assert calls == {"guides": 1, "stock": 1}
        records = resumed['observations']
        assert {r['tool'] for r in records.values()} == {'check_guide_availability', 'check_equipment_inventory'}
        stock = next(r for r in records.values() if r['tool'] == 'check_equipment_inventory')
        assert stock['result']['status'] == ('error' if inventory_fails else 'success')
        operations = [event["operation_id"] for event in context.trace.events
                      if event["type"] == "tool.called"]
        assert len(set(operations)) == 2
    asyncio.run(run())

"""Exercise the actual graph, interrupt, queues and booking boundary without an LLM server."""

import asyncio
import json
import re

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.evaluation.checks import evaluate
from app.simulation.config import Settings
from app.simulation.runner import SimulationRunner
from app.simulation.scenario import load_scenario


class ScriptedModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "test-script"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        calls = [m for m in messages if isinstance(m, ToolMessage)]
        rid = re.search(r"Request ID ([\w-]+)", messages[1].content).group(1)
        terms = dict(
            route_id="PR-PNPE-2",
            date="2026-11-10",
            guide_id="luis",
            equipment={"rain jacket": 1},
        )
        booking_id = f"tour-{rid}"
        steps_a = [
            ("ask_human", dict(question="What gear do you own?")),
            (
                "get_weather_forecast",
                dict(location="Picos de Europa", date=terms["date"]),
            ),
            (
                "search_hiking_routes",
                dict(location="Picos de Europa", difficulty="easy", max_hours=4),
            ),
            ("send_to_agent", dict(content=json.dumps(terms), kind="request")),
        ]
        steps_b = [
            (
                "check_guide_availability",
                dict(route_id=terms["route_id"], date=terms["date"]),
            ),
            (
                "check_equipment_inventory",
                dict(items=terms["equipment"], date=terms["date"]),
            ),
            (
                "ask_human",
                dict(
                    question="Choose Ines or Luis",
                    kind="selection",
                    options=["ines", "luis"],
                ),
            ),
            (
                "ask_human",
                dict(
                    question="Approve the displayed proposal?",
                    kind="approval",
                    proposal=terms,
                ),
            ),
        ]
        is_a = "You help a customer" in messages[0].content
        steps = steps_a if is_a else steps_b
        index = len(calls)
        if index < len(steps):
            name, args = steps[index]
        elif not is_a and index == 4:
            name, args = "create_tour_reservation", terms
        elif not is_a and index == 5:
            name, args = "send_to_agent", dict(content=booking_id, kind="response")
        elif (
            is_a and messages[-1].type == "human" and booking_id in messages[-1].content
        ):
            result = dict(
                request_id=rid,
                status="confirmed",
                route_id=terms["route_id"],
                date=terms["date"],
                guide_id="luis",
                reservation_id=booking_id,
                equipment_items=["rain jacket"],
            )
            name, args = (
                "submit_trip_result",
                dict(
                    result=result,
                    final_message=f"Confirmed PR-PNPE-2 on 2026-11-10 with luis. Reservation {booking_id}. Equipment: rain jacket.",
                ),
            )
        else:
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content="Waiting."))]
            )
        message = AIMessage(
            content="", tool_calls=[dict(name=name, args=args, id=f"call-{index}")]
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


def test_scripted_customer_booking():
    run = SimulationRunner(
        load_scenario("happy_path"), Settings(timeout=10), 42, ScriptedModel()
    )
    asyncio.run(run.run())
    assert run.error is None, run.error
    assert evaluate(run)["passed"]
    assert run.humans["agent_a"].messages

"""Exercise the actual graph, interrupt, queues and booking boundary without an LLM server."""

import asyncio
import json
import re
import pytest

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.evaluation.checks import evaluate
from app.simulation.config import Settings
from app.simulation.runner import SimulationRunner
from app.simulation.scenario import load_scenario


class ScriptedModel(BaseChatModel):
    case_id: str = "happy_path"
    accepts_substitution: bool = True

    @property
    def _llm_type(self):
        return "test-script"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        calls = [m for m in messages if isinstance(m, ToolMessage)]
        rid = re.search(r"Request ID ([\w-]+)", messages[1].content).group(1)
        terms = dict(
            route_id="PR-PNPE-2:long",
            date="2026-11-10",
            guide_id="luis",
            equipment={"rain jacket": 1},
        )
        if self.case_id in ("bad_weather", "guide_unavailable"):
            terms["date"] = "2026-11-11"
        recovery = self.case_id in ("hitl_rejection", "equipment_shortage")
        original = dict(terms)
        if self.case_id == "guide_unavailable":
            original["date"] = "2026-11-10"
        if recovery:
            terms["equipment"] = {"poncho": 1}
        steps_a = [
            ("ask_human", dict(question="What gear do you own?")),
            (
                "get_weather_forecast",
                dict(location="Picos de Europa", date=original["date"]),
            ),
            (
                "search_hiking_routes",
                dict(location="Picos de Europa", difficulty="easy", max_hours=4, keywords=['Enol']),
            ),
            ("send_to_agent", dict(content=json.dumps(original), kind="request",
                proposal={key: original[key] for key in ("route_id", "date", "equipment")})),
        ]
        steps_b = [
            (
                "check_guide_availability",
                dict(route_id=terms["route_id"], date=terms["date"]),
            ),
            (
                "check_equipment_inventory",
                dict(items=original["equipment"], date=terms["date"]),
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
                    proposal=original,
                ),
            ),
        ]
        if self.case_id == "bad_weather":
            steps_a[1:1] = [
                (
                    "get_weather_forecast",
                    dict(location="Picos de Europa", date="2026-11-10"),
                ),
                ("ask_human", dict(question="Do you confirm the alternative date?")),
            ]
        if self.case_id == "guide_unavailable":
            steps_b[-1] = ("send_to_agent", dict(content="Please confirm the revised hike on November 11.", kind="response"))
            steps_b += [
                ("send_to_agent", dict(content="Here is the complete verified alternative.", kind="response", proposal=terms)),
                ("ask_human", dict(question="Approve revised hike?", kind="approval", proposal=terms)),
            ]
            steps_a += [
                ("send_to_agent", dict(content="Please send the full verified proposal including the selected guide.", kind="request")),
                ("get_weather_forecast", dict(location="Picos de Europa", date=terms["date"])),
                ("ask_human", dict(question="Do you accept this alternative?", proposal=terms)),
                ("reply_with_customer_decision", dict(decision="accepted")),
            ]
            steps_b.insert(
                0,
                (
                    "check_guide_availability",
                    dict(date="2026-11-10", route_id=terms["route_id"]),
                ),
            )
        if recovery:
            steps_a += [
                ("ask_human", dict(question="Do you accept the poncho substitution?", proposal=terms)),
                ("reply_with_customer_decision", dict(
                    decision="accepted" if self.accepts_substitution else "declined")),
            ]
            if self.case_id == "equipment_shortage":
                steps_b.pop()
            steps_b += [
                (
                    "check_equipment_inventory",
                    dict(items={"poncho": 1}, date=terms["date"]),
                ),
                ("send_to_agent", dict(content="Please offer the verified poncho substitution to the customer.", kind="request", proposal=terms)),
            ]
            if self.accepts_substitution:
                steps_b += [
                    (
                        "ask_human",
                        dict(
                            question="Approve the customer-accepted revised proposal?",
                            kind="approval",
                            proposal=terms,
                        ),
                    )]
            else:
                steps_b += [("send_to_agent", dict(content="Customer declined the substitution; no reservation was created.", kind="response"))]
        is_a = "You help a customer" in messages[0].content
        steps = steps_a if is_a else steps_b
        index = len(calls)
        if index < len(steps):
            name, args = steps[index]
        elif not is_a and index == len(steps_b) and self.accepts_substitution:
            name, args = "create_tour_reservation", terms
        elif not is_a and index == len(steps_b) + 1 and self.accepts_substitution:
            booking = json.loads(calls[-1].content)["data"]
            name, args = "send_to_agent", dict(
                content="Reservation confirmed " + booking["reservation_id"], kind="response", proposal=terms)
        elif is_a and recovery and not self.accepts_substitution and index == len(steps_a):
            name, args = "submit_trip_result", dict(
                result=dict(status="failed", failure_reason="Customer declined the poncho substitution."),
            )
        elif (
            is_a and messages[-1].type == "human" and "Reservation confirmed" in messages[-1].content
        ):
            result = dict(
                status="confirmed",
                route_id=terms["route_id"],
                date=terms["date"],
                guide_id="luis",
                equipment_items=list(terms["equipment"]),
            )
            name, args = (
                "submit_trip_result",
                dict(
                    result=result,
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


@pytest.mark.parametrize(
    "case_id",
    [
        "happy_path",
        "bad_weather",
        "guide_unavailable",
        "hitl_rejection",
        "external_service_failure",
    ],
)
def test_scripted_customer_booking(case_id):
    run = SimulationRunner(
        load_scenario(case_id), Settings(timeout=15), 42, ScriptedModel(case_id=case_id)
    )
    asyncio.run(run.run())
    assert run.error is None, run.error
    assert evaluate(run)["passed"]
    assert run.humans["agent_a"].messages


def test_customer_declining_manager_substitution_finishes_without_booking():
    case = load_scenario("hitl_rejection")
    case["rules"]["substitution"][1] = "No, I do not accept the poncho substitution."
    case["substitution_accepted"] = False
    run = SimulationRunner(case, Settings(timeout=15), 42,
                           ScriptedModel(case_id="hitl_rejection", accepts_substitution=False))
    asyncio.run(run.run())
    assert run.error is None, run.error
    assert run.result.status == "failed"
    assert not any(e['type'] == 'tool.completed' and e['data'].get('tool') == 'create_tour_reservation' for e in run.trace.events)
    assert not run.provider.created
    assert evaluate(run)["passed"]
    decisions = [e for e in run.trace.events if e["type"] == "human.response"
                 and e["actor"] == "human_b" and "approval_ref" in e["data"]]
    assert len(decisions) == 1

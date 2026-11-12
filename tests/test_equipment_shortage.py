"""Exercise both customer decisions through the actual two-agent graph."""

import asyncio

import pytest

from app.evaluation.checks import evaluate
from app.simulation.config import Settings
from app.simulation.runner import SimulationRunner
from app.simulation.scenario import load_scenario
from test_integration import ScriptedModel


@pytest.mark.parametrize("accepted", [True, False])
def test_equipment_shortage_requires_customer_choice_before_manager(accepted):
    case = load_scenario("equipment_shortage")
    case["substitution_accepted"] = accepted
    if not accepted:
        case["rules"]["substitution"][1] = "No, I do not accept the poncho substitution."
    run = SimulationRunner(case, Settings(timeout=15), 42,
                           ScriptedModel(case_id="equipment_shortage", accepts_substitution=accepted))
    asyncio.run(run.run())
    assert run.error is None, run.error
    report = evaluate(run)
    assert report["passed"], report["checks"]
    assert run.result.status == ("confirmed" if accepted else "failed")
    manager_approvals = [event for event in run.trace.events
                         if event["type"] == "human.response" and event["actor"] == "human_b"
                         and "approval_ref" in event["data"]]
    assert len(manager_approvals) == int(accepted)
    bookings = [event['data']['output']['data'] for event in run.trace.events
                if event['type'] == 'tool.completed' and event['data'].get('tool') == 'create_tour_reservation']
    assert len(bookings) == int(accepted)
    if accepted:
        assert bookings[0]['equipment'] == {'poncho': 1}
    else:
        assert run.humans['agent_a'].messages

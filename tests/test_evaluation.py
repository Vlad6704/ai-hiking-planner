from app.evaluation.checks import metrics
import copy
import pytest


def test_evaluator_enforces_explicit_expected_route_but_allows_unconstrained_routes():
    import asyncio
    from app.evaluation.checks import evaluate
    from app.simulation.runner import SimulationRunner
    from app.simulation.scenario import load_scenario
    from app.simulation.config import Settings
    from test_integration import ScriptedModel

    run = SimulationRunner(load_scenario('happy_path'), Settings(timeout=15), 42, ScriptedModel())
    asyncio.run(run.run())
    assert evaluate(run)['passed']
    run.case['expected_route_id'] = 'PR-PNPE-2:short'
    assert evaluate(run)['checks']['route'] is False
    run.case.pop('expected_route_id')
    assert evaluate(run)['checks']['route'] is True


def test_route_details_are_sufficient_evidence_but_an_id_alone_is_not():
    import asyncio
    from app.evaluation.checks import evaluate
    from app.simulation.runner import SimulationRunner
    from app.simulation.scenario import load_scenario
    from app.simulation.config import Settings
    from test_integration import ScriptedModel

    run = SimulationRunner(load_scenario('happy_path'), Settings(timeout=15), 42, ScriptedModel())
    asyncio.run(run.run())
    assert evaluate(run)['passed']
    search = next(event for event in run.trace.events if event['type'] == 'tool.completed'
                  and event['data'].get('tool') == 'search_hiking_routes')
    details = copy.deepcopy(search)
    details['data']['tool'] = 'get_route_details'
    details['data']['output']['data'] = next(route for route in search['data']['output']['data']
                                            if route['route_id'] == run.result.route_id)
    run.trace.events.insert(run.trace.events.index(search), details)
    run.trace.events = [event for event in run.trace.events if not (
        event['type'] == 'tool.completed' and event['data'].get('tool') == 'search_hiking_routes')]
    assert evaluate(run)['checks']['route'] is True
    details['data']['output']['status'] = 'error'
    assert evaluate(run)['checks']['route'] is False
    details['data']['output']['status'] = 'degraded'
    assert evaluate(run)['checks']['route'] is True
    run.trace.events = [event for event in run.trace.events if not (
        event['type'] == 'tool.completed' and event['data'].get('tool') == 'get_route_details')]
    assert evaluate(run)['checks']['route'] is False


def test_evaluation_does_not_require_runner_business_state():
    import time
    from types import SimpleNamespace
    from app.evaluation.checks import evaluate

    run = SimpleNamespace(
        trace=SimpleNamespace(events=[], started=time.monotonic()), result=None,
        case={"id": "happy_path", "expected_date": "2026-11-10", "weather_failure": False},
        settings=SimpleNamespace(steps=100, attempts=3), usage={}, error=None,
    )
    report = evaluate(run)
    assert report["passed"] is False
    assert report["checks"]["approved_booking"] is False


def substitution_events(case_id="hitl_rejection"):
    """A hand-authored successful substitution with explicit causal evidence."""
    original = dict(route_id="r", date="2026-11-10", guide_id="g", equipment={"rain jacket": 1})
    revised = {**original, "equipment": {"poncho": 1}}
    events = []

    def add(identifier, kind, actor, data, parent=None, operation=None):
        events.append(dict(event_id=identifier, seq=len(events) + 1, type=kind,
                           actor=actor, caused_by=parent, operation_id=operation, data=data))

    def inventory(item, available):
        add(item + "-call", "tool.called", "agent_b",
            dict(tool="check_equipment_inventory", arguments=dict(date="2026-11-10", items={item: 1})), operation=item)
        add(item + "-stock", "tool.completed", "agent_b",
            dict(tool="check_equipment_inventory", output=dict(data=dict(
                quantities={item: 3 if available else 0}, unavailable=[] if available else [item]))), operation=item)

    add("initial", "agent.message_sent", "agent_a", dict(message_id="initial", type="request", proposal=original))
    inventory("rain jacket", case_id == "hitl_rejection")
    if case_id == "hitl_rejection":
        add("reject-prompt", "human.interrupt", "agent_b", dict(proposal=original, kind="approval"))
        add("reject", "human.response", "human_b", dict(proposal=original, approval_ref=None), "reject-prompt")
    inventory("poncho", True)
    add("offer", "agent.message_sent", "agent_b", dict(message_id="offer", type="response", correlation_id="initial", proposal=revised))
    add("offer-received", "agent.message_received", "agent_a", dict(message_id="offer", type="response", correlation_id="initial", proposal=revised), "offer")
    add("customer-prompt", "human.interrupt", "agent_a", dict(kind="substitution", proposal=revised), "offer-received")
    add("customer", "human.response", "human_a", dict(text="Sounds good to me", proposal=revised), "customer-prompt")
    add("consent", "customer.consent", "agent_a", dict(accepted=True, proposal=revised,
        response_event_id="customer", offer_message_id="offer"), "customer")
    add("decision", "agent.message_sent", "agent_a", dict(message_id="decision", type="request", proposal=revised), "consent")
    add("decision-received", "agent.message_received", "agent_b", dict(message_id="decision", type="request", proposal=revised), "decision")
    add("approve-prompt", "human.interrupt", "agent_b", dict(kind="approval", proposal=revised), "decision-received")
    add("approve", "human.response", "human_b", dict(proposal=revised, approval_ref="fresh"), "approve-prompt")
    add("booking-call", "tool.called", "agent_b", dict(tool="create_tour_reservation", arguments=revised), operation="booking")
    add("booking", "tool.completed", "agent_b", dict(tool="create_tour_reservation", output=dict(data={**revised, "reservation_id": "one"})), operation="booking")
    return events


@pytest.mark.parametrize("case_id", ["hitl_rejection", "equipment_shortage"])
def test_substitution_evaluator_accepts_verified_causal_recovery(case_id):
    from app.evaluation.checks import substitution_checks
    assert all(substitution_checks(substitution_events(case_id), case_id).values())


@pytest.mark.parametrize("mutation", [
    "missing_consent", "late_consent", "early_approval", "wrong_consent_terms",
    "wrong_reply_parent", "unverified_substitute", "rejected_reservation",
    "unavailable_original", "substitute_before_rejection", "wrong_source_reply", "decision_after_approval",
])
def test_substitution_evaluator_rejects_invalid_recovery(mutation):
    from app.evaluation.checks import substitution_checks
    events = substitution_events()
    indexed = {event["event_id"]: event for event in events}
    if mutation == "missing_consent":
        events.remove(indexed["customer"])
    elif mutation == "late_consent":
        events.remove(indexed["customer"])
        events.append(indexed["customer"])
    elif mutation == "early_approval":
        events.remove(indexed["approve"])
        events.insert(0, indexed["approve"])
    elif mutation == "wrong_consent_terms":
        indexed["customer"]["data"]["proposal"] = copy.deepcopy(indexed["initial"]["data"]["proposal"])
    elif mutation == "wrong_reply_parent":
        indexed["decision"]["caused_by"] = "initial"
    elif mutation == "unverified_substitute":
        indexed["poncho-stock"]["data"]["output"]["data"]["quantities"]["poncho"] = 0
    elif mutation == "rejected_reservation":
        indexed["booking"]["data"]["output"]["data"]["equipment"] = {"rain jacket": 1}
    elif mutation == "unavailable_original":
        indexed["rain jacket-stock"]["data"]["output"]["data"]["unavailable"] = ["rain jacket"]
    elif mutation == "substitute_before_rejection":
        events.remove(indexed["poncho-stock"])
        events.insert(0, indexed["poncho-stock"])
    elif mutation == "wrong_source_reply":
        indexed["consent"]["data"]["response_event_id"] = "reject"
    elif mutation == "decision_after_approval":
        events.remove(indexed["consent"])
        events.append(indexed["consent"])
    for seq, event in enumerate(events, 1):
        event["seq"] = seq
    assert not all(substitution_checks(events, "hitl_rejection").values())


def test_metric_denominators():
    report = metrics(
        [
            {"type": kind, "data": {}}
            for kind in ["tool.called", "tool.failed", "tool.called", "tool.completed"]
        ]
    )
    assert report["tool_failure_rate"] == 0.5
    assert report["recovery_success_rate"] is None


def test_reapproval_after_booking_does_not_invalidate_previous_creation():
    from app.evaluation.checks import approved_bookings

    terms = {"route_id": "r", "date": "2026-11-10", "guide_id": "g", "equipment": {}}

    def approve(seq):
        return {
            "type": "human.response",
            "actor": "human_b",
            "seq": seq,
            "data": {
                "approval_ref": str(seq),
                "proposal": terms,
                "matched_intent": ["approval"],
            },
        }

    def event(seq, kind, op):
        return {
            "type": kind,
            "seq": seq,
            "operation_id": op,
            "data": {
                "tool": "create_tour_reservation",
                "output": {"data": {**terms, "reservation_id": "same"}},
            },
        }

    first = [approve(1), event(2, "tool.called", "a"), event(3, "tool.completed", "a")]
    assert approved_bookings(
        first
        + [approve(4), event(5, "tool.called", "b"), event(6, "tool.completed", "b")]
    )
    assert not approved_bookings(first[1:] + [approve(4)])


def test_evaluation_exports_token_reporting_coverage():
    import time
    from types import SimpleNamespace
    from app.evaluation.checks import evaluate
    from app.observability.langsmith import Usage
    usage = Usage()
    usage.calls = 2
    usage.reported = 1
    usage.input_tokens = 100
    usage.output_tokens = 5
    run = SimpleNamespace(trace=SimpleNamespace(events=[],started=time.monotonic()),result=None,
        case={'id':'happy_path','expected_date':'2026-11-10','weather_failure':False},
        settings=SimpleNamespace(steps=100, attempts=3),usage={'agent_a':usage},error=None)
    metrics = evaluate(run)['metrics']
    assert metrics['token_usage_reported_calls'] == 1
    assert metrics['llm_call_count'] == 2
    assert metrics['per_agent']['agent_a']['input_tokens'] == 100

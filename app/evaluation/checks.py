import time
from collections import Counter


def ratio(part, total):
    return part / total if total else None


def metrics(events):
    counts = Counter(e["type"] for e in events)
    usage = [e["data"] for e in events if e["type"] == "model.completed"]
    return dict(
        llm_call_count=len(usage),
        input_tokens=sum(u.get("input_tokens", 0) for u in usage) if usage else None,
        output_tokens=sum(u.get("output_tokens", 0) for u in usage) if usage else None,
        tool_failure_rate=ratio(counts["tool.failed"], counts["tool.called"]),
        recovery_success_rate=ratio(
            counts["recovery.applied"], counts["recovery.started"]
        ),
        agent_interaction_count=counts["agent.message_sent"],
        human_matching_failure_rate=ratio(
            sum(
                e["type"] == "human.response" and not e["data"]["matched_intent"]
                for e in events
            ),
            counts["human.response"],
        ),
    )


def approved_bookings(events):
    """Check the approval in effect when each successful booking attempt began."""
    current = None
    calls = {}
    successful = 0
    for event in events:
        data = event["data"]
        if event["type"] == "human.response" and event["actor"] == "human_b":
            if "approval_ref" in data:
                current = data["proposal"] if data["approval_ref"] else None
            elif "selection" in data.get("matched_intent", []):
                current = None
        if data.get("tool") != "create_tour_reservation":
            continue
        if event["type"] == "tool.called":
            calls[event["operation_id"]] = current
        if event["type"] == "tool.completed":
            approved = calls.get(event["operation_id"])
            receipt = data["output"]["data"]
            if not approved or any(receipt.get(k) != v for k, v in approved.items()):
                return False
            successful += 1
    return successful > 0


def evaluate(run):
    events = run.trace.events
    result = run.result
    booking = getattr(getattr(run, "operator", None), "result", None)
    deliveries = [e for e in events if e["type"] == "human.message_delivered"]
    confirmed = bool(result and result.status == "confirmed")
    checks = dict(
        confirmed=confirmed,
        expected_date=bool(
            confirmed
            and str(result.date)
            in run.case.get("acceptable_dates", [run.case["expected_date"]])
        ),
        route=bool(confirmed and result.route_id == "PR-PNPE-2"),
        guide=bool(
            confirmed
            and result.guide_id == run.selected
            and any(
                g["guide_id"] == result.guide_id
                and g["available"]
                and result.route_id in g["qualifications"]
                for group in run.observed.get("check_guide_availability", [])
                for g in group
            )
        ),
        approved_booking=bool(
            booking
            and run.approvals.records.get(run.rid)
            and confirmed
            and booking.reservation_id == result.reservation_id
        ),
        communication=run.bus.count >= 2,
        within_limits=len(events) <= run.settings.steps,
        delivery=bool(
            len(deliveries) == 1
            and events[-1]["type"] == "simulation.completed"
            and events[-1]["caused_by"] == deliveries[0]["event_id"]
            and deliveries[0]["recipient"] == "human_a"
            and result
            and deliveries[0]["data"]["trip_result"] == result.model_dump(mode="json")
        ),
    )
    creations = [
        e
        for e in events
        if e["type"] == "tool.completed"
        and e["data"]["tool"] == "create_tour_reservation"
    ]
    checks["approval_before_booking"] = approved_bookings(events)
    checks["unique_reservation"] = (
        len({e["data"]["output"]["data"]["reservation_id"] for e in creations}) == 1
    )
    attempts = [e["data"]["attempt"] for e in events if e["type"] == "tool.called"]
    checks["bounded_attempts"] = all(1 <= n <= run.settings.attempts for n in attempts)
    valid_pairs = {
        ("agent_a", "human_a"),
        ("agent_b", "human_b"),
        ("human_a", "agent_a"),
        ("human_b", "agent_b"),
        ("agent_a", "agent_b"),
        ("agent_b", "agent_a"),
    }
    checks["participant_routing"] = all(
        (e["actor"], e["recipient"]) in valid_pairs
        for e in events
        if e["type"]
        in (
            "human.message",
            "human.interrupt",
            "human.response",
            "human.message_delivered",
            "agent.message_sent",
        )
    )
    checks["weather_suitable"] = bool(
        result
        and any(
            day["date"] == str(result.date)
            and day["wind_kmh"] <= 40
            and day["precipitation_probability"] <= 70
            for forecast in run.observed.get("get_weather_forecast", [])
            for day in forecast["days"]
        )
    )
    expected_rental = "poncho" if run.case["id"] == "hitl_rejection" else "rain jacket"
    checks["required_equipment"] = bool(
        booking and booking.equipment.get(expected_rental, 0) >= 1
    )
    if run.case["id"] == "guide_unavailable":
        checks["original_guide_shortage"] = [] in run.observed.get(
            "check_guide_availability", []
        )
    if run.case["id"] == "bad_weather":
        checks["unsafe_date_checked"] = any(
            day["wind_kmh"] > 40
            for forecast in run.observed.get("get_weather_forecast", [])
            for day in forecast["days"]
        )
    if run.case["weather_failure"]:
        checks["fallback"] = any(e["type"] == "recovery.applied" for e in events)
    if len(run.case["decisions"]) > 1:
        checks["rejection_and_reapproval"] = (
            any(
                e["type"] == "human.response"
                and e["data"]["text"].startswith("Rejected")
                for e in events
            )
            and checks["approved_booking"]
        )
    values = metrics(events)
    values["per_agent"] = {
        actor: dict(
            llm_call_count=u.calls,
            input_tokens=u.input_tokens if u.reported else None,
            output_tokens=u.output_tokens if u.reported else None,
        )
        for actor, u in run.usage.items()
    }
    for key in ("llm_call_count", "input_tokens", "output_tokens"):
        counts = [
            entry[key]
            for entry in values["per_agent"].values()
            if entry[key] is not None
        ]
        values[key] = sum(counts) if counts else None
    values.update(
        task_success_rate=int(confirmed),
        scenario_pass_rate=int(all(checks.values())),
        latency_ms=round((time.monotonic() - run.trace.started) * 1000),
    )
    return dict(
        trip_result=result.model_dump(mode="json") if result else None,
        outcome="completed" if result else "failed",
        passed=all(checks.values()),
        checks=checks,
        metrics=values,
        error=run.error,
    )

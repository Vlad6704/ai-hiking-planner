import time
from collections import Counter


def ratio(part, total):
    return part / total if total else None


def cache_totals(per_agent):
    active = [entry for entry in per_agent.values() if entry["llm_call_count"]]
    totals = {}
    for key in ("cached_input_tokens", "cache_write_tokens"):
        known = active and all(entry[key] is not None for entry in active)
        totals[key] = sum(entry[key] for entry in active) if known else None
    for key in ("cache_read_reported_calls", "cache_write_reported_calls"):
        totals[key] = sum(entry[key] for entry in active)
    inputs = sum(entry["input_tokens"] or 0 for entry in active)
    cached = totals["cached_input_tokens"]
    totals["cache_read_ratio"] = ratio(cached, inputs) if cached is not None else None
    return totals


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


def substitution_checks(events, case_id, accepted=True):
    """Validate equipment recovery using exact terms and recorded causal links."""
    from copy import deepcopy
    events = deepcopy(events)
    for event in events:
        payload = event['data'].get('payload') or {}
        if payload.get('kind') in ('trip_offer', 'customer_decision'):
            event['data']['proposal'] = payload['proposal']
        elif payload.get('kind') == 'trip_request':
            event['data']['proposal'] = payload['terms']
    indexed = {event["event_id"]: event for event in events}

    def before(first, second):
        return first["seq"] < second["seq"]

    def descends(event, ancestor):
        seen = set()
        while event.get("caused_by") in indexed:
            parent = indexed[event["caused_by"]]
            if parent["event_id"] in seen or not before(parent, event):
                return False
            if parent["event_id"] == ancestor["event_id"]:
                return True
            seen.add(parent["event_id"])
            event = parent
        return False

    def received(message, actor):
        return [event for event in events if event["type"] == "agent.message_received"
                and event["actor"] == actor
                and event["data"].get("message_id") == message["data"].get("message_id")
                and descends(event, message)]

    inventory = []
    for completed in events:
        if completed["type"] != "tool.completed" or completed["data"].get("tool") != "check_equipment_inventory":
            continue
        calls = [event for event in events if event["type"] == "tool.called"
                 and event["data"].get("tool") == "check_equipment_inventory"
                 and event.get("operation_id") == completed.get("operation_id")
                 and before(event, completed)]
        if calls:
            inventory.append((calls[-1], completed, completed["data"]["output"]["data"]))

    def stock(item, available):
        return [(call, done) for call, done, output in inventory
                if call["data"]["arguments"].get("items", {}).get(item, 0) >= 1
                and ((item not in output.get("unavailable", [])
                      and output.get("quantities", {}).get(item, 0)
                      >= call["data"]["arguments"]["items"][item]) == available)]

    original_stock = stock("rain jacket", case_id == "hitl_rejection")
    substitute_stock = stock("poncho", True)
    rejections = [event for event in events if event["type"] == "human.response"
                  and event["actor"] == "human_b" and "approval_ref" in event["data"]
                  and not event["data"]["approval_ref"]
                  and event["data"].get("proposal", {}).get("equipment", {}).get("rain jacket", 0) >= 1]
    creations = [event for event in events if event["type"] == "tool.completed"
                 and event["data"].get("tool") == "create_tour_reservation"]
    rejected_terms = [event["data"]["proposal"] for event in rejections]
    checks = dict(
        requested_inventory=bool(original_stock),
        substitute_inventory=bool(substitute_stock),
        customer_substitution_decision=False,
        substitution_causal_order=False,
        single_reservation_operation=(len({event.get("operation_id") for event in creations}) == int(accepted)),
    )
    if case_id == "hitl_rejection":
        checks["rejection_and_reapproval"] = False
        checks["rejected_terms_not_reserved"] = all(
            not all(creation["data"]["output"]["data"].get(key) == value for key, value in terms.items())
            for creation in creations for terms in rejected_terms)

    offers = [event for event in events if event["type"] == "agent.message_sent"
              and event["actor"] == "agent_b"
              and event["data"].get("proposal", {}).get("equipment", {}).get("poncho", 0) >= 1]
    for offer in offers:
        terms = offer["data"]["proposal"]
        verified = [(call, done) for call, done in substitute_stock
                    if call["data"]["arguments"]["date"] == terms["date"] and before(done, offer)]
        triggers = rejections if case_id == "hitl_rejection" else [done for _, done in original_stock]
        valid_triggers = [trigger for trigger in triggers
                          if any(before(trigger, call) for call, _ in verified)
                          and (case_id != "hitl_rejection" or any(
                              before(done, trigger) and call["data"]["arguments"]["date"] == terms["date"]
                              for call, done in original_stock))]
        for offer_received in received(offer, "agent_a"):
            questions = [event for event in events if event["type"] == "human.interrupt"
                         and event["actor"] == "agent_a" and event["data"].get("proposal") == terms
                         and descends(event, offer_received)]
            decisions = [event for event in events if event["type"] == "customer.consent"
                         and event["actor"] == "agent_a" and event["data"].get("proposal") == terms
                         and event["data"].get("accepted") is accepted
                         and event["data"].get("response_event_id") == event.get("caused_by")
                         and event["data"].get("offer_message_id") == offer["data"].get("message_id")
                         and event.get("caused_by") in indexed
                         and indexed[event["caused_by"]]["type"] == "human.response"
                         and indexed[event["caused_by"]]["actor"] == "human_a"
                         and indexed[event["caused_by"]]["data"].get("proposal") == terms
                         and any(descends(event, question) for question in questions)]
            checks["customer_substitution_decision"] |= bool(decisions)
            replies = [event for event in events if event["type"] == "agent.message_sent"
                       and event["actor"] == "agent_a" and event["data"].get("proposal") == terms
                       and any(descends(event, decision) for decision in decisions)]
            decision_received = [event for reply in replies for event in received(reply, "agent_b")]
            approvals = [event for event in events if event["type"] == "human.response"
                         and event["actor"] == "human_b" and event["data"].get("approval_ref")
                         and event["data"].get("proposal") == terms
                         and any(descends(event, receipt) for receipt in decision_received)]
            if accepted:
                booked = any(
                    all(creation["data"]["output"]["data"].get(key) == value for key, value in terms.items())
                    and any(call["type"] == "tool.called"
                            and call["data"].get("tool") == "create_tour_reservation"
                            and call.get("operation_id") == creation.get("operation_id")
                            and call["data"].get("arguments") == terms
                            and before(call, creation) and any(before(approval, call) for approval in approvals)
                            for call in events)
                    for creation in creations)
                complete = bool(valid_triggers and decision_received and approvals and booked)
            else:
                later_approvals = [event for event in events if event["type"] == "human.response"
                                   and event["actor"] == "human_b" and "approval_ref" in event["data"]
                                   and any(before(decision, event) for decision in decisions)]
                complete = bool(valid_triggers and decision_received and not creations and not later_approvals)
            checks["substitution_causal_order"] |= complete
            if case_id == "hitl_rejection":
                checks["rejection_and_reapproval"] |= complete
    return checks


def evaluate(run):
    events = run.trace.events
    result = run.result
    observed = {}
    selected = None
    approval = None
    booking = None
    for event in events:
        data = event["data"]
        if event["type"] == "tool.completed":
            value = data.get("output", {}).get("data")
            route_error = (data.get('tool') in ('search_hiking_routes', 'get_route_details')
                           and data.get('output', {}).get('status') == 'error')
            if value is not None and not route_error:
                observed.setdefault(data["tool"], []).append(value)
                if data["tool"] == "create_tour_reservation":
                    booking = value
        elif event["type"] == "recovery.applied":
            # The fallback is evidence of a completed weather observation.
            observed.setdefault("get_weather_forecast", []).append(data["outcome"])
        elif event["type"] == "human.response" and event["actor"] == "human_b":
            if data.get("guide_id"):
                selected = data["guide_id"]
                approval = None
            if "approval_ref" in data:
                approval = data if data["approval_ref"] else None
    deliveries = [e for e in events if e["type"] == "human.message_delivered"]
    confirmed = bool(result and result.status == "confirmed")
    verified_routes = [route for group in observed.get('search_hiking_routes', []) for route in group]
    verified_routes.extend(observed.get('get_route_details', []))
    checks = dict(
        confirmed=confirmed,
        expected_date=bool(
            confirmed
            and str(result.date)
            in run.case.get("acceptable_dates", [run.case["expected_date"]])
        ),
        route=bool(confirmed
            and (not run.case.get('expected_route_id') or result.route_id == run.case['expected_route_id'])
            and any(
            route["route_id"] == result.route_id
            for route in verified_routes)),
        guide=bool(
            confirmed
            and result.guide_id == selected
            and any(
                g["guide_id"] == result.guide_id
                and g["available"]
                and result.route_id in g["qualifications"]
                for group in observed.get("check_guide_availability", [])
                for g in group
            )
        ),
        approved_booking=bool(
            booking
            and approval
            and confirmed
            and booking["reservation_id"] == result.reservation_id
        ),
        communication=sum(event["type"] == "agent.message_sent" for event in events) >= 2,
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
            for forecast in observed.get("get_weather_forecast", [])
            for day in forecast["days"]
        )
    )
    recovery = run.case["id"] in ("hitl_rejection", "equipment_shortage")
    accepted = run.case.get("substitution_accepted", True)
    expected_rental = "poncho" if recovery else "rain jacket"
    checks["required_equipment"] = bool(
        booking and booking["equipment"].get(expected_rental, 0) >= 1
    )
    if run.case["id"] == "guide_unavailable":
        checks["original_guide_shortage"] = [] in observed.get(
            "check_guide_availability", []
        )
    if run.case["id"] == "bad_weather":
        checks["unsafe_date_checked"] = any(
            day["wind_kmh"] > 40
            for forecast in observed.get("get_weather_forecast", [])
            for day in forecast["days"]
        )
    if run.case["weather_failure"]:
        checks["fallback"] = any(e["type"] == "recovery.applied" for e in events)
    if recovery:
        if not accepted:
            for key in ("confirmed", "expected_date", "route", "guide", "approved_booking",
                        "approval_before_booking", "unique_reservation", "weather_suitable", "required_equipment"):
                checks.pop(key)
            checks["expected_outcome"] = bool(result and result.status == "failed" and result.failure_reason)
            checks["no_reservation"] = booking is None and not creations
        checks.update(substitution_checks(events, run.case["id"], accepted))
    values = metrics(events)
    values["per_agent"] = {
        actor: dict(
            llm_call_count=u.calls,
            parallel_tool_batches=u.parallel_tool_batches,
            input_tokens=u.input_tokens if u.reported else None,
            output_tokens=u.output_tokens if u.reported else None,
            **u.cache_metrics(),
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
    values.update(cache_totals(values["per_agent"]))
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

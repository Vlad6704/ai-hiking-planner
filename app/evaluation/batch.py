"""Pure aggregation of the runs requested by one CLI invocation."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from statistics import mean, median


@dataclass
class RunRecord:
    case_id: str
    scenario: str
    repetition: int
    context: dict
    started: bool = False
    run_id: str | None = None
    request_id: str | None = None
    report: dict | None = None
    trajectory_path: Path | None = None
    error: dict | None = None
    events: list | None = None


@dataclass
class BatchRecord:
    batch_id: str
    started_at: str
    context: dict
    runs: list[RunRecord]
    finished_at: str | None = None
    wall_time_ms: int = 0
    interrupted: bool = False


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def number(value):
    return {"value": value}


def ratio(n, d):
    return dict(value=n / d if d else None, numerator=n, denominator=d)


def booking_receipt(record):
    for event in reversed(record.events or []):
        data = event.get("data", {})
        output = data.get("output") or {}
        receipt = output.get("data") or {}
        if event.get("type") == "tool.completed" and data.get("tool") == "create_tour_reservation" and output.get("status") in ("success", "degraded") and isinstance(receipt, dict) and receipt.get("reservation_id"):
            return {key: receipt.get(key) for key in ("reservation_id", "route_id", "date", "guide_id", "equipment")}
    return None


def passed(record):
    return bool((record.report or {}).get("passed")) and not record.error and not (record.report or {}).get("error")


def report_error_code(error):
    """Preserve known runtime codes without publishing raw exception text."""
    code = str(error).split(":", 1)[0]
    return code if code in {"deadlock", "peer_timeout", "step_limit", "TimeoutError", "GraphRecursionError", "delivery_failed"} else "runtime_error"


def aggregate(records):
    reports = [r.report for r in records if r.report is not None]
    n = len(records)
    errors = [r for r in records if r.error or (r.report or {}).get("error")]
    business = [(r.report or {}).get("trip_result") or {} for r in records]
    counts = Counter()
    for r, result in zip(records, business):
        kind = "runtime_error" if r in errors else "confirmed_execution" if result.get("status") == "confirmed" else "controlled_failed_trip" if result.get("status") == "failed" else "incomplete_run"
        counts[kind + "_count"] += 1
    m = {key: number(counts[key]) for key in ("runtime_error_count", "confirmed_execution_count", "controlled_failed_trip_count", "incomplete_run_count")}
    pass_count = sum(passed(r) for r in records)
    confirmed = sum(booking_receipt(r) is not None for r in records)
    m.update(planned_run_count=number(n), started_run_count=number(sum(r.started for r in records)), reported_run_count=number(len(reports)), missing_report_count=number(n-len(reports)), not_started_run_count=number(sum(not r.started for r in records)), passed_run_count=number(pass_count), scenario_pass_rate=ratio(pass_count,n), confirmed_booking_count=number(confirmed), booking_confirmation_rate=ratio(confirmed,n))
    for label, subset in (("", reports), ("passed_", [r.report for r in records if r.report is not None and passed(r)]), ("non_passed_", [r.report for r in records if r.report is not None and not passed(r)])):
        values = [p.get("metrics", {}).get("latency_ms") for p in subset]
        values = [v for v in values if v is not None]
        m[label+"latency_sample_count"] = number(len(values))
        for name, fn in (("mean", mean), ("median", median), ("maximum", max)):
            m[label+"latency_"+name+"_ms"] = number(fn(values) if values else None)
    scopes = {"overall": [(r.report or {}).get("metrics", {}) for r in records]}
    actors = sorted({a for p in reports for a in p.get("metrics", {}).get("per_agent", {})})
    for actor in actors:
        scopes[actor] = [(r.report or {}).get("metrics", {}).get("per_agent", {}).get(actor, {}) for r in records]
    usage = {}
    for scope, entries in scopes.items():
        entries = [dict(e) for e in entries]
        for entry in entries:
            if entry.get("llm_call_count") == 0:
                for key in ("input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens", "token_usage_reported_calls", "cache_read_reported_calls", "cache_write_reported_calls"):
                    entry[key] = 0
        u = {}
        for key, coverage in (("llm_call_count", None), ("input_tokens", "token_usage_reported_calls"), ("output_tokens", "token_usage_reported_calls"), ("cached_input_tokens", "cache_read_reported_calls"), ("cache_write_tokens", "cache_write_reported_calls")):
            observed = [e.get(key + "_observed", e.get(key)) for e in entries if e.get(key + "_observed", e.get(key)) is not None]
            measured = [e[key] for e in entries if e.get(key) is not None and (coverage is None or e.get(coverage) == e.get("llm_call_count") and e.get(coverage) is not None)]
            u[key] = dict(value=sum(measured) if len(measured)==len(entries) and entries else None, observed_subtotal=sum(observed) if observed else None, measured_run_count=len(measured), planned_run_count=len(entries))
            if key in ("llm_call_count", "input_tokens", "output_tokens"):
                u["mean_"+key] = dict(value=mean(measured) if measured else None, denominator=len(measured))
        for key in ("token_usage_reported_calls", "cache_read_reported_calls", "cache_write_reported_calls"):
            values = [e.get(key) for e in entries]
            u[key] = dict(value=sum(values) if all(v is not None for v in values) else None, observed_subtotal=sum(v for v in values if v is not None))
        cached, tokens = u["cached_input_tokens"]["value"], u["input_tokens"]["value"]
        u["cache_read_ratio"] = ratio(cached, tokens) if cached is not None and tokens is not None else dict(value=None, numerator=cached, denominator=tokens)
        usage[scope] = u
    m.update(usage.pop("overall"))
    tools = defaultdict(Counter)
    all_events = [e for r in records for e in (r.events or [])]
    event_names = {"tool.called":"tool_attempt_count", "tool.failed":"failed_tool_attempt_count", "tool.retry":"tool_retry_count", "recovery.started":"fallback_attempt_count", "recovery.applied":"successful_fallback_count"}
    for e in all_events:
        if e["type"] in event_names:
            tools[e.get("data", {}).get("tool", "unknown")][event_names[e["type"]]] += 1
    def tool_metrics(c):
        out = {v: number(c[v]) for v in event_names.values()}
        out["tool_failure_rate"] = ratio(c["failed_tool_attempt_count"], c["tool_attempt_count"])
        out["fallback_success_rate"] = ratio(c["successful_fallback_count"], c["fallback_attempt_count"])
        return out
    m.update(tool_metrics(sum(tools.values(), Counter())))
    m["agent_message_count"] = number(sum(e["type"]=="agent.message_sent" for e in all_events))
    checks = defaultdict(Counter)
    for p in reports:
        for key, value in p.get("checks", {}).items():
            checks[key]["reported"] += 1
            checks[key]["failed"] += int(value is False)
    m["check_failures"] = {k: dict(value=v["failed"], denominator=v["reported"]) for k,v in checks.items()}
    m["error_codes"] = dict(Counter((r.error or {}).get("code") or report_error_code((r.report or {}).get("error")) for r in errors))
    m["per_agent"] = usage
    m["per_tool"] = {k: tool_metrics(v) for k,v in tools.items()}
    return m


def summarize_batch(batch):
    groups = defaultdict(list)
    scenarios = defaultdict(list)
    for r in batch.runs:
        scenarios[r.scenario].append(r)
        groups[(r.scenario, fingerprint(r.context))].append(r)
    comparisons = []
    for (scenario, context_id), records in groups.items():
        distribution = {}
        successful = Counter()
        for r in records:
            result = (r.report or {}).get("trip_result")
            if not result:
                continue
            normalized = {k: result.get(k) for k in ("status", "route_id", "date", "guide_id")}
            normalized["equipment_items"] = sorted(result.get("equipment_items") or [])
            key = fingerprint(normalized)
            distribution.setdefault(key, dict(result=normalized, count=0))["count"] += 1
            if result.get("status")=="confirmed" and (r.report or {}).get("passed") and not r.error and not r.report.get("error"):
                successful[key] += 1
        comparisons.append(dict(scenario=scenario, context_fingerprint=context_id, business_results=list(distribution.values()), successful_repeatability=ratio(max(successful.values(), default=0), len(records))))
    return dict(schema_version=1, batch_id=batch.batch_id, started_at=batch.started_at, finished_at=batch.finished_at, context=batch.context, incomplete=batch.interrupted or any(r.report is None for r in batch.runs), runs=[dict(case_id=r.case_id, scenario=r.scenario, repetition=r.repetition, started=r.started, run_id=r.run_id, request_id=r.request_id, context=r.context, evaluation=r.report, booking_receipt=booking_receipt(r), error=r.error, trajectory=None) for r in batch.runs], overall={**aggregate(batch.runs), "batch_wall_time_ms":number(batch.wall_time_ms)}, per_scenario={k:aggregate(v) for k,v in scenarios.items()}, comparison_groups=comparisons)

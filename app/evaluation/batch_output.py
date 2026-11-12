"""Portable, redacted batch artifacts and presentation."""
import json
import os
from pathlib import Path
import subprocess
from app.evaluation.batch import summarize_batch, report_error_code
from app.observability.trace import redact

PRIMARY = ("scenario_pass_rate", "runtime_error_count", "latency_mean_ms", "latency_median_ms", "latency_maximum_ms", "input_tokens", "mean_input_tokens", "output_tokens", "mean_output_tokens", "cached_input_tokens", "cache_write_tokens", "cache_read_ratio", "llm_call_count", "mean_llm_call_count")
COVERAGE = ("planned_run_count", "reported_run_count", "latency_sample_count")


def allocate_report_directory(root):
    """Reserve the next numbered folder without overwriting concurrent runs."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    number = max((int(p.name) for p in root.iterdir() if p.is_dir() and p.name.isascii() and p.name.isdigit()), default=0) + 1
    while True:
        directory = root / f"{number:06d}"
        try:
            directory.mkdir()
            return directory
        except FileExistsError:
            number += 1


def source_context(root):
    try:
        def git(*args):
            return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=2, check=True).stdout.strip()
        return dict(revision=git("rev-parse", "HEAD"), dirty=bool(git("status", "--porcelain")))
    except (OSError, subprocess.SubprocessError):
        return dict(revision=None, dirty=None)


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


LABELS = {
    "scenario_pass_rate": "Scenario checks passed",
    "runtime_error_count": "Runtime errors",
    "latency_mean_ms": "Average run time",
    "latency_median_ms": "Median run time",
    "latency_maximum_ms": "Longest run time",
    "input_tokens": "Total input tokens",
    "mean_input_tokens": "Average input tokens per run",
    "output_tokens": "Total output tokens",
    "mean_output_tokens": "Average output tokens per run",
    "cached_input_tokens": "Cached input tokens",
    "cache_write_tokens": "Cache-write tokens",
    "cache_read_ratio": "Input served from cache",
    "llm_call_count": "Total model calls",
    "mean_llm_call_count": "Average model calls per run",
    "planned_run_count": "Planned runs",
    "reported_run_count": "Reported runs",
    "latency_sample_count": "Runs with timing data",
}


CHECK_LABELS = {
    "confirmed": "Booking confirmed",
    "expected_date": "Expected date selected",
    "route": "Route matches requirements",
    "guide": "Guide matches requirements",
    "approved_booking": "Booking matches approved proposal",
    "communication": "Required agent communication completed",
    "within_limits": "Execution stayed within limits",
    "delivery": "Final result delivered",
    "approval_before_booking": "Approval received before booking",
    "unique_reservation": "No duplicate reservations",
    "bounded_attempts": "Tool attempts stayed within limits",
    "participant_routing": "Messages routed to correct participants",
    "weather_suitable": "Weather suitable for selected trip",
    "required_equipment": "Required equipment included",
}


def label(key):
    return LABELS.get(key, key.replace("_", " ").capitalize())


def formatted(key, entry):
    value = entry.get("value")
    if value is None:
        text = "Unavailable"
        subtotal = entry.get("observed_subtotal")
        if subtotal is not None:
            text += f" (observed subtotal: {subtotal:,}; complete runs: {entry.get('measured_run_count', 0)})"
        return text
    if key.endswith("_ms"):
        return f"{value / 1000:,.1f} s"
    if key.endswith("_rate") or key.endswith("_ratio") or key == "repeatability":
        percent = f"{value * 100:.1f}".removesuffix(".0") + "%"
        if key in ("scenario_pass_rate", "booking_confirmation_rate", "repeatability"):
            return f"{entry['numerator']:,} of {entry['denominator']:,} ({percent})"
        return percent
    text = f"{value:,}" if isinstance(value, int) else f"{value:,.1f}"
    if key.startswith("mean_") and entry.get("denominator") is not None:
        text += f" (from {entry['denominator']:,} runs)"
    return text


def metric_rows(metrics, keys, prefix=""):
    rows = []
    for key in keys:
        entry = metrics[key]
        name = prefix + label(key)
        if isinstance(entry, dict) and "value" in entry:
            rows.append((name, formatted(key, entry)))
        elif isinstance(entry, dict):
            for nested, value in entry.items():
                if isinstance(value, dict) and "value" not in value:
                    rows.extend(metric_rows(value, value.keys(), name + " / " + label(nested) + " / "))
                else:
                    scalar = value if isinstance(value, dict) else {"value": value}
                    rows.append((name + " / " + label(nested), formatted(nested, scalar)))
    return rows


def sections(summary, name, metrics):
    primary = metric_rows(metrics, [k for k in PRIMARY if k in metrics])
    for group in summary["comparison_groups"]:
        if name == "Overall" or name == group["scenario"]:
            primary.insert(1, ("Same successful trip result (" + group["scenario"] + ")", formatted("repeatability", group["successful_repeatability"])))
    return [("Primary metrics", primary),
            ("Sample size and coverage", metric_rows(metrics, [k for k in COVERAGE if k in metrics])),
            ("Diagnostic metrics", metric_rows(metrics, [k for k in metrics if k not in PRIMARY + COVERAGE]))]


def diagnostic_sections(metrics):
    groups = [
        ("Execution outcomes", ("confirmed_execution_count", "controlled_failed_trip_count", "runtime_error_count", "incomplete_run_count", "passed_run_count", "confirmed_booking_count", "booking_confirmation_rate")),
        ("Run accounting", ("started_run_count", "missing_report_count", "not_started_run_count")),
        ("Successful run timing", tuple(k for k in metrics if k.startswith("passed_latency_"))),
        ("Unsuccessful run timing", tuple(k for k in metrics if k.startswith("non_passed_latency_"))),
        ("Usage coverage", ("token_usage_reported_calls", "cache_read_reported_calls", "cache_write_reported_calls")),
        ("Tool reliability", ("tool_attempt_count", "failed_tool_attempt_count", "tool_retry_count", "fallback_attempt_count", "successful_fallback_count", "tool_failure_rate", "fallback_success_rate")),
        ("Communication", ("agent_message_count",)),
        ("Batch timing", ("batch_wall_time_ms",)),
    ]
    result = []
    for title, keys in groups:
        rows = metric_rows(metrics, [k for k in keys if k in metrics])
        if title.endswith("run timing"):
            prefix = "passed_" if title.startswith("Successful") else "non_passed_"
            timing_labels = {"latency_sample_count": "Runs with timing data", "latency_mean_ms": "Average run time", "latency_median_ms": "Median run time", "latency_maximum_ms": "Longest run time"}
            rows = [(timing_labels.get(k.removeprefix(prefix), label(k)), formatted(k, metrics[k])) for k in keys]
        if rows:
            result.append((title, rows))
    checks = metrics.get("check_failures", {})
    if checks:
        result.append(("Scenario checks", [(label(k) + " failures", f"{v['value']:,} of {v['denominator']:,} checked runs") for k, v in checks.items()]))
    errors = metrics.get("error_codes", {})
    if errors:
        result.append(("Runtime error codes", [(label(k), f"{v:,}") for k, v in errors.items()]))
    for actor, values in metrics.get("per_agent", {}).items():
        result.append((actor.replace("_", " ").title(), metric_rows(values, values.keys())))
    for tool, values in metrics.get("per_tool", {}).items():
        result.append((label(tool), metric_rows(values, values.keys())))
    return result


def coverage_note(metrics):
    usage = metrics.get("input_tokens", {})
    count = usage.get("measured_run_count", 0)
    total = usage.get("planned_run_count", 0)
    return f"Token usage reported for all {total} runs." if total and count == total else f"Complete token usage reported for {count} of {total} runs."


def render_markdown(summary):
    lines = ["# Automated batch summary", "", "Batch: " + summary["batch_id"], ""]
    for name, metrics in [("Overall", summary["overall"]), *summary["per_scenario"].items()]:
        lines += ["## " + cell(name), ""]
        for heading, rows in sections(summary, name, metrics):
            if heading == "Diagnostic metrics":
                lines += ["### Diagnostic metrics", ""]
                for title, diagnostic_rows in diagnostic_sections(metrics):
                    if title == "Scenario checks":
                        lines += ["#### Scenario checks", "", "Missing or inapplicable check results are excluded from both counts.", "", "| Check | Passed | Failed |", "|---|---:|---:|"]
                        for key, entry in metrics.get("check_failures", {}).items():
                            failed = entry["value"]
                            passed = entry["denominator"] - failed
                            lines.append(f"| {cell(CHECK_LABELS.get(key, label(key)))} | {passed:,} | {failed:,} |")
                        lines.append("")
                        continue
                    lines += ["#### " + cell(title), "", "| Metric | Result |", "|---|---:|"]
                    lines += ["| " + cell(k) + " | " + cell(v) + " |" for k, v in diagnostic_rows]
                    lines.append("")
                continue
            lines += ["### " + heading, "", "| Metric | Result |", "|---|---:|"]
            lines += ["| " + cell(k) + " | " + cell(v) + " |" for k, v in rows]
            lines.append("")
            if heading == "Primary metrics":
                lines += [coverage_note(metrics), ""]
    lines += ["## Run artifacts", ""]
    for run in summary["runs"]:
        ref = run["trajectory"]
        lines.append("- " + cell(run["scenario"]) + " #" + str(run["repetition"]) + ": " + ("[trajectory](<" + ref + ">)" if ref else "Unavailable"))
    lines += ["", "## Comparison details", ""]
    for group in summary["comparison_groups"]:
        lines += ["### " + cell(group["scenario"]), "", "Configuration fingerprint: `" + group["context_fingerprint"] + "`", "", "| Status | Route | Date | Guide | Equipment | Runs |", "|---|---|---|---|---|---:|"]
        for result in group["business_results"]:
            facts = result["result"]
            values = [facts.get(k) or "Unavailable" for k in ("status", "route_id", "date", "guide_id")]
            values += [", ".join(facts.get("equipment_items") or []) or "None", result["count"]]
            lines.append("| " + " | ".join(cell(v) for v in values) + " |")
        lines.append("")
    return "\n".join(lines)


def render_console(summary):
    lines = ["Automated batch " + summary["batch_id"]]
    for name, metrics in [("Overall", summary["overall"]), *summary["per_scenario"].items()]:
        lines.append(name)
        for heading, rows in sections(summary, name, metrics)[:2]:
            lines.append(heading)
            width = max((len(k) for k, _ in rows), default=0)
            lines.extend(f"  {k:<{width}}  {v}" for k, v in rows)
        lines.append(coverage_note(metrics))
        failures = [(name, entry) for name, entry in metrics.get("check_failures", {}).items() if entry.get("value")]
        lines.append("Failed checks: " + (", ".join(f"{label(k)}: {v['value']} of {v['denominator']}" for k, v in failures) or "None"))
        lines.append("Runtime error codes: " + (", ".join(f"{k}: {v}" for k, v in metrics.get("error_codes", {}).items()) or "None"))
    return "\n".join(lines)


def write_batch_summary(batch, directory):
    directory = Path(directory)
    document = summarize_batch(batch)
    for record, entry in zip(batch.runs, document["runs"]):
        try:
            entry["trajectory"] = Path(os.path.relpath(record.trajectory_path.resolve(), directory.resolve())).as_posix() if record.trajectory_path and record.trajectory_path.exists() else None
        except ValueError:
            entry["trajectory"] = None
        if entry["trajectory"] is None:
            entry["trajectory_unavailable"] = "missing_or_nonportable"
        if entry["evaluation"]:
            entry["evaluation"] = dict(entry["evaluation"])
            if entry["evaluation"].get("error"):
                entry["evaluation"]["error"] = report_error_code(entry["evaluation"]["error"])
    document = redact(document)
    directory.mkdir(parents=True, exist_ok=True)
    paths = directory / "summary.json", directory / "summary.md"
    for path, text in zip(paths, (json.dumps(document, ensure_ascii=False, indent=2), render_markdown(document))):
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)
    return paths

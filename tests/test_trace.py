import json

from app.observability.trace import TraceRecorder


def test_concurrent_events_and_redaction(tmp_path):
    trace = TraceRecorder({"scenario_id": "case", "run_id": "run"})
    first = trace.emit("simulation.started", "runner", {"Authorization": "secret"})
    last = trace.emit(
        "simulation.failed",
        "runner",
        {"reason": "timeout"},
        caused_by=first["event_id"],
    )
    document = json.loads(trace.write(tmp_path, {}).read_text())
    assert [event["seq"] for event in document["events"]] == [1, 2]
    assert last["caused_by"] == first["event_id"]
    assert "secret" not in str(document)

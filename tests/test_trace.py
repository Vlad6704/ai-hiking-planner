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


def test_automated_trajectories_remain_grouped_by_scenario(tmp_path):
    trace = TraceRecorder({"scenario_id": "case", "run_id": "run"})
    assert trace.write(tmp_path, {}) == tmp_path / "case" / "run.json"


def test_flat_trajectory_preserves_scenario_in_metadata(tmp_path):
    trace = TraceRecorder({"scenario_id": "case", "run_id": "run"})
    path = trace.write(tmp_path, {}, group_by_scenario=False)
    assert path == tmp_path / "run.json"
    assert json.loads(path.read_text())["metadata"]["scenario_id"] == "case"
    assert list(tmp_path.iterdir()) == [path]

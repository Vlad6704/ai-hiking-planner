import asyncio
import json
import sys

import pytest

from app.simulation import __main__ as cli


def test_parallel_runs_overlap_and_keep_separate_trajectories(monkeypatch, tmp_path):
    active = set()
    started = []
    original = cli.SimulationRunner

    async def check():
        ready = asyncio.Event()

        def build(case, settings, seed):
            run = original(case, settings, seed)

            async def execute():
                active.add(run.rid)
                started.append(run.rid)
                if len(active) == 4:
                    ready.set()
                await asyncio.wait_for(ready.wait(), timeout=2)
                active.remove(run.rid)

            run.run = execute
            return run

        monkeypatch.setattr(cli, "SimulationRunner", build)
        monkeypatch.setattr(cli, "scenarios", lambda: ["happy_path", "bad_weather"])
        monkeypatch.setattr(cli, "evaluate", lambda run: {"passed": run.case["id"] == "happy_path"})
        monkeypatch.setattr(sys, "argv", ["hiking", "--all", "--parallel", "--runs", "2", "--output", str(tmp_path)])
        assert await cli.main() == 1

    asyncio.run(check())
    assert len(set(started)) == 4
    assert len(list(tmp_path.glob("*/*.json"))) == 4
    assert not active


def test_cli_modes_and_runs(monkeypatch, tmp_path):
    seen = []
    original = cli.SimulationRunner

    def build(case, settings, seed):
        run = original(case, settings, seed)
        seen.append((case["id"], run.rid, seed))
        return run

    monkeypatch.setattr(cli, "SimulationRunner", build)
    monkeypatch.delenv("OPERATOR_URL", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hiking",
            "--scenario",
            "happy_path",
            "--runs",
            "5",
            "--mode",
            "real",
            "--seed",
            "42",
            "--output",
            str(tmp_path),
        ],
    )
    assert asyncio.run(cli.main()) == 1
    assert len({entry[1] for entry in seen}) == 5
    assert {entry[2] for entry in seen} == {42}
    paths = list(tmp_path.glob("happy_path/*.json"))
    assert len(paths) == 5
    for path in paths:
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert {"passed", "checks", "metrics"} <= doc['result'].keys()
        assert "OPERATOR_URL" in doc["result"]["error"]
        assert doc["events"][-1]["type"] == "simulation.failed"


def test_reject_zero_runs(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["hiking", "--scenario", "happy_path", "--runs", "0"]
    )
    with pytest.raises(SystemExit) as exc:
        asyncio.run(cli.main())
    assert exc.value.code == 2


def test_default_output_groups_automatic_runs_by_scenario(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPERATOR_URL", raising=False)
    monkeypatch.setattr(
        sys, "argv", ["hiking", "--scenario", "happy_path", "--mode", "real"]
    )
    assert asyncio.run(cli.main()) == 1
    root = tmp_path / "trajectories"
    paths = list(root.rglob("*.json"))
    assert len(paths) == 1
    assert paths[0].parent == root / "automatic" / "happy_path"
    assert {path.name for path in root.iterdir()} == {"automatic"}

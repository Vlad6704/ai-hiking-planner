import asyncio
import json
import sys

import pytest

from app.simulation import __main__ as cli


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
        assert "OPERATOR_URL" in doc["result"]["error"]
        assert doc["events"][-1]["type"] == "simulation.failed"


def test_reject_zero_runs(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["hiking", "--scenario", "happy_path", "--runs", "0"]
    )
    with pytest.raises(SystemExit) as exc:
        asyncio.run(cli.main())
    assert exc.value.code == 2

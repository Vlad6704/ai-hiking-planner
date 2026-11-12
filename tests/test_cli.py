import asyncio
import json
import sys

import pytest

from app.simulation import __main__ as cli


@pytest.fixture(autouse=True)
def isolated_cli_working_directory(monkeypatch, tmp_path):
    """Keep default report and trajectory output inside each test's workspace."""
    monkeypatch.chdir(tmp_path)


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
    assert len(list(tmp_path.glob("reports/automatic/*/summary.json"))) == 1
    assert len(list(tmp_path.glob("reports/automatic/*/summary.md"))) == 1


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
    assert len(list(tmp_path.glob("reports/automatic/*/summary.json"))) == 1
    assert len(list(tmp_path.glob("reports/automatic/*/summary.md"))) == 1
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


def test_batch_keeps_siblings_after_constructor_failure(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    original = cli.SimulationRunner
    calls = []
    def build(case, settings, seed):
        calls.append(case['id'])
        if len(calls) == 1:
            raise ValueError('secret C:/private/path')
        return original(case, settings, seed)
    monkeypatch.setattr(cli, 'SimulationRunner', build)
    monkeypatch.delenv('OPERATOR_URL', raising=False)
    monkeypatch.setattr(sys, 'argv', ['hiking', '--scenario', 'happy_path', '--mode', 'real', '--runs', '2', '--parallel'])
    assert asyncio.run(cli.main()) == 1
    files = list(tmp_path.glob('reports/automatic/*/summary.json'))
    assert len(files) == 1
    text = files[0].read_text()
    doc = json.loads(text)
    assert len(calls) == 2
    assert doc['overall']['planned_run_count']['value'] == 2
    assert 'secret' not in text


def test_cancelled_batch_is_saved(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    original = cli.SimulationRunner
    async def check():
        entered = asyncio.Event()
        def build(case, settings, seed):
            run = original(case, settings, seed)
            async def execute():
                entered.set()
                await asyncio.Event().wait()
            run.run = execute
            return run
        monkeypatch.setattr(cli, 'SimulationRunner', build)
        monkeypatch.setattr(sys, 'argv', ['hiking','--scenario','happy_path','--parallel','--runs','2'])
        task = asyncio.create_task(cli.main())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(check())
    doc = json.loads(next(tmp_path.glob('reports/automatic/*/summary.json')).read_text())
    assert doc['incomplete']
    assert len(doc['runs']) == 2
    assert doc['overall']['incomplete_run_count']['value'] == 2


@pytest.mark.parametrize('stage', ['execution','evaluation','trajectory_write'])
def test_batch_stage_failures_leave_other_runs(monkeypatch, tmp_path, stage):
    monkeypatch.chdir(tmp_path)
    original = cli.SimulationRunner
    count = 0
    def build(case, settings, seed):
        nonlocal count
        count += 1
        run = original(case, settings, seed)
        async def execute():
            if stage == 'execution' and run.rid == first[0]:
                raise ValueError('private path')
        if not first:
            first.append(run.rid)
        run.run = execute
        if stage == 'trajectory_write' and count == 1:
            def fail(*args):
                raise OSError('private path')
            run.trace.write = fail
        return run
    first = []
    def evaluate(run):
        if stage == 'evaluation' and run.rid == first[0]:
            raise ValueError('private path')
        return {'passed': True, 'checks': {}, 'metrics': {}}
    monkeypatch.setattr(cli,'SimulationRunner',build)
    monkeypatch.setattr(cli,'evaluate',evaluate)
    monkeypatch.setattr(sys,'argv',['hiking','--scenario','happy_path','--parallel','--runs','2'])
    assert asyncio.run(cli.main()) == 1
    doc = json.loads(next(tmp_path.glob('reports/automatic/*/summary.json')).read_text())
    assert len(doc['runs']) == 2
    assert sum(r['error'] is not None for r in doc['runs']) == 1
    assert doc['overall']['runtime_error_count']['value'] == 1

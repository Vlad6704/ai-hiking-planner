import argparse
import asyncio
import json
from pathlib import Path
import time
from uuid import uuid4
from app.observability.trace import now
from app.evaluation.batch import BatchRecord, RunRecord, fingerprint, summarize_batch
from app.evaluation.batch_output import write_batch_summary, render_console, source_context, allocate_report_directory
from app.route_catalog.seed import SEED_PATH
from app.agents.factory import configured_model

from app.observability.runtime_logging import configure_logging

if __name__ == '__main__':
    configure_logging('simulation')

from app.evaluation.checks import evaluate
from app.simulation.config import Settings
from app.simulation.failures import FAILURE_TOOLS, FailureInjection, apply_failure_override
from app.simulation.runner import SimulationRunner
from app.simulation.scenario import load_scenario, scenarios


async def main():
    configure_logging('simulation')
    parser = argparse.ArgumentParser(
        description="Run the Picos de Europa multi-agent simulation"
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--scenario", choices=scenarios())
    selection.add_argument("--all", action="store_true")
    parser.add_argument("--mode", choices=["real", "mock"], default="mock")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--parallel", action="store_true", help="Run selected simulations concurrently in one process")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument('--failure-tool', choices=FAILURE_TOOLS)
    parser.add_argument('--timeout-probability', type=float)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--peer-timeout", type=float, default=30)
    parser.add_argument("--output", type=Path, default=Path("trajectories/automatic"))
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    if (args.failure_tool is None) != (args.timeout_probability is None):
        parser.error('--failure-tool and --timeout-probability must be used together')
    override = None
    if args.failure_tool is not None:
        if args.mode != 'mock':
            parser.error('Failure injection is available only in mock mode')
        try:
            override = FailureInjection(tool=args.failure_tool, timeout_probability=args.timeout_probability)
        except ValueError as exc:
            parser.error(str(exc))

    settings = Settings(mode=args.mode, timeout=args.timeout, peer_timeout=args.peer_timeout)
    context = dict(mode=args.mode, parallel=args.parallel, seed=args.seed, settings=settings.model_dump(mode="json"), **source_context(Path.cwd()))
    model_name = configured_model()
    context.update(scenarios=scenarios() if args.all else [args.scenario], repetitions=args.runs,
                   model=model_name, temperature=1 if model_name == "openai:gpt-6-luna" else None if model_name == "openai:gpt-6-sol" else 0,
                   failure_override=override.model_dump(mode="json") if override else None)
    names = [name for name in (scenarios() if args.all else [args.scenario]) for _ in range(args.runs)]
    records = [RunRecord(str(uuid4()), name, i % args.runs + 1, dict(context)) for i, name in enumerate(names)]
    batch = BatchRecord(str(uuid4()), now(), context, records)
    try:
        directory = allocate_report_directory(Path("reports/automatic"))
    except OSError:
        print("Batch summary directory creation failed", flush=True)
        return 1
    started = time.monotonic()
    publication_failed = False

    def persist():
        nonlocal publication_failed
        batch.wall_time_ms = round((time.monotonic() - started) * 1000)
        try:
            return write_batch_summary(batch, directory)
        except OSError:
            publication_failed = True
            print("Batch summary publication failed", flush=True)
            return None

    if persist() is None:
        return 1

    async def run_case(record):
        run = None
        stage = "scenario_load"
        record.started = True
        try:
            case = apply_failure_override(load_scenario(record.scenario, args.mode), override)
            record.context.update(fixture_fingerprint=fingerprint(case), failure_injection=case.get("failure_injection", {}))
            seed_document = json.loads(SEED_PATH.read_text(encoding="utf-8")) if args.mode == "mock" else None
            record.context["catalog_seed"] = fingerprint(seed_document) if seed_document else None
            record.context["catalog_seed_id"] = seed_document.get("seed_id") if seed_document else None
            stage = "construction"
            run = SimulationRunner(case, settings, args.seed)
            record.run_id = run.trace.metadata["run_id"]
            record.request_id = run.rid
            record.context.update(model=run.trace.metadata.get("model"), temperature=run.trace.metadata.get("temperature"))
            stage = "execution"
            await run.run()
            stage = "evaluation"
            record.report = evaluate(run)
            stage = "trajectory_write"
            record.trajectory_path = run.trace.write(args.output, record.report)
            print(json.dumps(dict(path=str(record.trajectory_path), **record.report)), flush=True)
        except Exception as exc:
            record.error = dict(stage=stage, type=type(exc).__name__, code=stage + "_failed")
            if run is not None and record.report is None:
                try:
                    record.report = evaluate(run)
                except Exception:
                    pass
            if run is not None and stage != "trajectory_write":
                try:
                    record.trajectory_path = run.trace.write(args.output, record.report)
                    if record.report is not None:
                        print(json.dumps(dict(path=str(record.trajectory_path), **record.report)), flush=True)
                except Exception:
                    record.error["trajectory_write_failed"] = True
        finally:
            if run is not None:
                record.events = list(run.trace.events)
            persist()

    tasks = []
    try:
        if args.parallel:
            tasks = [asyncio.create_task(run_case(record)) for record in records]
            await asyncio.gather(*tasks)
        else:
            for record in records:
                await run_case(record)
    except BaseException:
        batch.interrupted = True
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    finally:
        batch.finished_at = now()
        paths = persist()
    print(render_console(summarize_batch(batch)), flush=True)
    if paths:
        print("Batch artifacts: " + str(paths[0]) + ", " + str(paths[1]), flush=True)
    return 0 if not publication_failed and all(r.report and r.report.get("passed") and not r.report.get("error") and not r.error for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

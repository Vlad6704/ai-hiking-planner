import argparse
import asyncio
import json
from pathlib import Path

from app.observability.runtime_logging import configure_logging

if __name__ == '__main__':
    configure_logging('simulation')

from app.evaluation.checks import evaluate
from app.simulation.config import Settings
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
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--peer-timeout", type=float, default=30)
    parser.add_argument("--output", type=Path, default=Path("trajectories"))
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    passed = True
    for name in scenarios() if args.all else [args.scenario]:
        for _ in range(args.runs):
            run = SimulationRunner(
                load_scenario(name, args.mode),
                Settings(
                    mode=args.mode, timeout=args.timeout, peer_timeout=args.peer_timeout
                ),
                args.seed,
            )
            await run.run()
            report = evaluate(run)
            path = run.trace.write(args.output, report)
            print(json.dumps(dict(path=str(path), **report)), flush=True)
            passed &= report["passed"]
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

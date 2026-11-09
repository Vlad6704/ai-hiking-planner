"""Publish console ownership before importing the agent runtime."""

import argparse
import importlib
import sys
import logging
from pathlib import Path

from app.simulation.launcher import write_status
from app.observability.runtime_logging import configure_logging


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--ready-file", type=Path, required=True)
    args, _ = parser.parse_known_args()
    path = args.ready_file

    def cancelled():
        return not path.parent.is_dir() or (path.parent / "cancelled").exists()

    if cancelled():
        return 0
    role = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ('operator', 'customer') else 'bootstrap'
    configure_logging('manual-' + role)
    try:
        write_status(path, "starting")
    except FileNotFoundError:
        return 0
    if cancelled():
        return 0
    try:
        manual = importlib.import_module("app.simulation.manual")
    except Exception as exc:
        logging.getLogger('app.manual').exception('console.import_failed')
        if cancelled():
            return 0
        try:
            write_status(path, "error", error=str(exc))
        except FileNotFoundError:
            return 0
        print(f"Console startup failed: {exc}", file=sys.stderr)
        return 1
    if cancelled():
        return 0
    sys.argv[0] = "app.simulation.manual"
    return manual.main()


if __name__ == "__main__":
    raise SystemExit(main())

"""Two local human consoles for one shared hiking simulation."""

import argparse
import asyncio
import json
import math
import socket
from pathlib import Path

from app.evaluation.checks import evaluate
from app.humans.simulator import HumanSimulator
from app.simulation.config import Settings
from app.simulation.launcher import launch, write_status
from app.simulation.manual_services import operator_backend
from app.simulation.runner import SimulationRunner
from app.simulation.scenario import load_scenario, scenarios


def manager_answer(prompt, read=input, show=print):
    show(f"\nOperator: {prompt['question']}")
    if prompt["kind"] == "selection":
        options = prompt["options"]
        if not options:
            return ""
        for number, guide in enumerate(options, 1):
            show(f"  {number}. {guide}")
        while True:
            answer = read("Manager (option number): ").strip()
            if answer in {str(i) for i in range(1, len(options) + 1)}:
                return answer
            show("Enter one of the displayed option numbers.")
    if prompt["kind"] == "approval":
        show(json.dumps(prompt["proposal"], indent=2, ensure_ascii=False))
        while True:
            answer = read("Manager (approve / reject): ").strip().lower()
            if answer == "approve":
                return "Approved"
            if answer == "reject":
                reason = read("Reason or requested change: ").strip()
                return f"Rejected. {reason}".strip()
            show("Enter approve or reject.")
    return read("Manager: ").strip()


def operator_console(port, ready_file=None):
    write_status(ready_file, "starting")
    try:
        server = socket.create_server(("127.0.0.1", port))
    except OSError as exc:
        write_status(ready_file, "error", error=str(exc))
        raise
    with server:
        write_status(ready_file, "ready", port=server.getsockname()[1])
        print(f"Agent B | Tour operator | Listening on 127.0.0.1:{server.getsockname()[1]}", flush=True)
        conn, _ = server.accept()
        with conn, conn.makefile("r", encoding="utf-8") as incoming:
            print("Customer terminal connected. Waiting for the operator's question.", flush=True)
            for line in incoming:
                message = json.loads(line)
                if "finished" in message:
                    print(f"Session ended: {message['finished']}")
                    return
                answer = manager_answer(message)
                conn.sendall((json.dumps(answer) + "\n").encode())
            print("Customer terminal disconnected.")


class CustomerConsole(HumanSimulator):
    async def deliver(self, agent_id, message_id, text):
        print(f"\nPlanner: {text}", flush=True)
        await super().deliver(agent_id, message_id, text)


class ManualRun(SimulationRunner):
    async def resolve_interrupt(self, actor, item):
        if actor == "agent_a":
            print(f"\nPlanner: {item.value['question']}", flush=True)
            answer = await asyncio.to_thread(input, "Customer: ")
        else:
            self.writer.write((json.dumps(item.value) + "\n").encode())
            await self.writer.drain()
            line = await self.reader.readline()
            if not line:
                raise RuntimeError("Operator terminal disconnected")
            answer = json.loads(line)
        return self.human_reply(actor, item, answer.strip())


async def customer_console(port, scenario, ready_file=None, mode="mock"):
    write_status(ready_file, "starting")
    try:
        with operator_backend(mode):
            return await connected_customer(port, scenario, ready_file, mode)
    except (OSError, RuntimeError, ValueError) as exc:
        if ready_file is not None:
            try:
                write_status(ready_file, 'error', error=str(exc))
            except FileNotFoundError:
                pass
        raise


async def connected_customer(port, scenario, ready_file, mode):
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
    except OSError as exc:
        write_status(ready_file, "error", error=str(exc))
        raise
    try:
        case = load_scenario(scenario, mode)
        print(f"Agent A | Travel planner | {mode} services")
        print(f"Enter your request or press Enter for: {case['initial']}")
        write_status(ready_file, "ready", port=port)
        case["initial"] = input("Customer: ").strip() or case["initial"]
        run = ManualRun(case, Settings(mode=mode, timeout=3600, peer_timeout=900), 42)
        run.reader, run.writer = reader, writer
        run.humans["agent_a"] = CustomerConsole({})
        print("Planner is working. Answer the manager prompts in the other terminal.", flush=True)
        await run.run()
        outcome = run.error or run.result.status
        print(f"Session ended: {outcome}")
        report = evaluate(run)
        path = run.trace.write(Path("trajectories/manual"), report)
        print(f"Trajectory: {path}")
        writer.write((json.dumps({"finished": outcome}) + "\n").encode())
        await writer.drain()
        return int(bool(run.error))
    finally:
        writer.close()
        await writer.wait_closed()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", nargs="?", choices=["launch", "operator", "customer"], default="launch",
                        help="Omit to open both terminals; use operator/customer for manual startup.")
    parser.add_argument("--port", type=int, default=18766)
    parser.add_argument("--scenario", choices=scenarios(), default="happy_path")
    parser.add_argument("--mode", choices=["mock", "real"], default="mock")
    parser.add_argument("--startup-timeout", type=float, default=30.0,
                        help="Seconds to wait for the operator when launching both terminals (default: 30).")
    parser.add_argument("--ready-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--keep-open", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    if not math.isfinite(args.startup_timeout) or args.startup_timeout <= 0:
        parser.error("--startup-timeout must be a finite positive number")
    try:
        if args.role == "launch":
            return launch(port=args.port, scenario=args.scenario, startup_timeout=args.startup_timeout, mode=args.mode)
        if args.role == "operator":
            operator_console(args.port, args.ready_file)
            return 0
        return asyncio.run(customer_console(args.port, args.scenario, args.ready_file, args.mode))
    except (OSError, RuntimeError, EOFError, KeyboardInterrupt) as exc:
        parser.exit(1, f"Manual session stopped: {exc or 'console closed'}.\n")
    finally:
        if args.keep_open:
            try:
                input("\nPress Enter to close this window...")
            except (EOFError, KeyboardInterrupt):
                pass


if __name__ == "__main__":
    raise SystemExit(main())

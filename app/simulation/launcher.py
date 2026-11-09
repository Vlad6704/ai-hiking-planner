"""Open the two manual consoles using the host's graphical terminal support."""

import json
import os
import platform
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import logging
from pathlib import Path

from app.observability.runtime_logging import log_path


FALLBACK = (
    "Open two terminals in the project root and run "
    "'uv run python -m app.simulation.manual operator', then "
    "'uv run --env-file .env python -m app.simulation.manual customer'."
)


def terminal_command(command: list[str], cwd: Path, *, system: str | None = None) -> tuple[list[str], dict]:
    system = system or platform.system()
    if system == "Windows":
        return command, {"creationflags": 0x00000010}  # CREATE_NEW_CONSOLE
    if system == "Darwin":
        dotenv = cwd / ".env"
        if dotenv.is_file():
            uv = shutil.which("uv")
            if not uv:
                raise RuntimeError(f"uv is required to load .env in macOS Terminal. {FALLBACK}")
            command = [uv, "run", "--no-sync", "--env-file", dotenv.as_posix(),
                       "--python", command[0], "python", *command[1:]]
        shell = f"cd {shlex.quote(cwd.as_posix())} && exec {shlex.join(command)}"
        script = 'tell application "Terminal" to do script ' + json.dumps(shell, ensure_ascii=False)
        return ["osascript", "-e", script], {"start_new_session": True}
    if system == "Linux" and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        shell = f"cd {shlex.quote(cwd.as_posix())} && exec {shlex.join(command)}"
        for name in ("gnome-terminal", "konsole", "x-terminal-emulator", "xterm"):
            executable = shutil.which(name)
            if executable:
                options = ["--window", "--wait", "--"] if name == "gnome-terminal" else ["-e"]
                if name == "konsole":
                    options.insert(0, "--separate")
                return [executable, *options, "/bin/sh", "-c", shell], {"start_new_session": True}
    raise RuntimeError(f"No supported graphical terminal is available on {system}. {FALLBACK}")


def open_terminal(command: list[str], cwd: Path) -> subprocess.Popen:
    argv, options = terminal_command(command, cwd)
    return subprocess.Popen(argv, cwd=cwd, **options)


def write_status(path: Path | None, state: str, **details) -> None:
    if path is not None:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"state": state, "pid": os.getpid(), **details}), encoding="utf-8")
        temporary.replace(path)


def wait_for_console(path: Path, process: subprocess.Popen, timeout: float, role: str) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            status = json.loads(path.read_text(encoding="utf-8"))
            if status["state"] == "error":
                raise RuntimeError(f"{role} startup failed: {status['error']}. Check its window and --port.")
            if status["state"] == "ready":
                return status
        code = process.poll()
        if code is not None and code != 0:
            raise RuntimeError(f"{role} terminal exited with code {code}. {FALLBACK}")
        time.sleep(0.05)
    raise RuntimeError(f"Timed out waiting for the {role.lower()}. Check its window or increase --startup-timeout. {FALLBACK}")


def stop_console(process: subprocess.Popen, status_file: Path) -> None:
    if status_file.is_file():
        pid = json.loads(status_file.read_text(encoding="utf-8"))["pid"]
        if pid != process.pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def launch(*, port: int = 18766, scenario: str = "happy_path", startup_timeout: float = 30.0, mode: str = "mock") -> int:
    cwd = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="picos-manual-") as directory:
        status_file = Path(directory) / "operator.json"
        customer_file = Path(directory) / "customer.json"
        operator = open_terminal(
            [sys.executable, "-m", "app.simulation.manual_bootstrap", "operator", "--port", str(port),
             "--ready-file", str(status_file), "--keep-open"], cwd,
        )
        customer = None
        try:
            status = wait_for_console(status_file, operator, startup_timeout, "Operator")
            customer = open_terminal(
                [sys.executable, "-m", "app.simulation.manual_bootstrap", "customer", "--port", str(status["port"]),
                 "--scenario", scenario, "--mode", mode, "--ready-file", str(customer_file), "--keep-open"], cwd,
            )
            wait_for_console(customer_file, customer, startup_timeout, "Customer")
        except BaseException:
            logging.getLogger('app.launcher').exception('launcher.failed')
            (Path(directory) / "cancelled").touch()
            if customer is not None:
                stop_console(customer, customer_file)
            stop_console(operator, status_file)
            raise
    print(f"Opened both manual terminals on 127.0.0.1:{status['port']}. Start in the customer window.")
    logging.getLogger('app.launcher').info('launcher.ready', extra={'fields': {'port': status['port'], 'operator_pid': operator.pid, 'customer_pid': customer.pid}})
    if log_path():
        print(f'Runtime logs: {log_path().parent}')
    return 0

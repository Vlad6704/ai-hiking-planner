import importlib
import json
import shlex
import socket
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.simulation import manual


@pytest.mark.parametrize("role", [[], ["launch"]])
def test_one_command_launches_selected_session(monkeypatch, role):
    launched = []
    monkeypatch.setattr(manual, "launch", lambda **args: launched.append(args) or 0, raising=False)
    monkeypatch.setattr(sys, "argv", ["manual", *role, "--port", "0", "--scenario", "hitl_rejection"])
    assert manual.main() == 0
    assert launched == [{"port": 0, "scenario": "hitl_rejection", "startup_timeout": 30.0, "mode": "mock"}]


def test_windows_launches_python_in_a_new_console(tmp_path):
    launcher = importlib.import_module("app.simulation.launcher")
    child = [r"C:\Python With Spaces\python.exe", "-m", "app.simulation.manual", "operator"]
    command, options = launcher.terminal_command(child, tmp_path, system="Windows")
    assert command == child
    assert options["creationflags"] & 0x10


def test_macos_preserves_quoted_paths_and_reloads_dotenv(monkeypatch, tmp_path):
    launcher = importlib.import_module("app.simulation.launcher")
    (tmp_path / ".env").write_text("HIKING_MODEL=ollama:test\n", encoding="utf-8")
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/opt/uv tools/uv" if name == "uv" else None)
    child = ["/Python With 'Quotes'/python", "-m", "app.simulation.manual", "customer"]
    command, _ = launcher.terminal_command(child, tmp_path, system="Darwin")
    assert command[:2] == ["osascript", "-e"]
    shell = json.loads(command[2].split("do script ", 1)[1])
    parts = shlex.split(shell)
    assert parts[:4] == ["cd", tmp_path.as_posix(), "&&", "exec"]
    assert parts[4:8] == ["/opt/uv tools/uv", "run", "--no-sync", "--env-file"]
    assert parts[8] == (tmp_path / ".env").as_posix()
    assert parts[-4:] == ["python", "-m", "app.simulation.manual", "customer"]


@pytest.mark.parametrize("terminal", ["gnome-terminal", "konsole", "x-terminal-emulator", "xterm"])
def test_linux_uses_available_terminal_without_shell_injection(monkeypatch, tmp_path, terminal):
    launcher = importlib.import_module("app.simulation.launcher")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(launcher.shutil, "which", lambda name: f"/usr/bin/{name}" if name == terminal else None)
    child = ["/python with spaces/python", "-m", "app.simulation.manual", "customer", "a'; echo injected"]
    command, _ = launcher.terminal_command(child, tmp_path, system="Linux")
    assert command[0] == f"/usr/bin/{terminal}"
    assert shlex.split(command[-1]) == ["cd", tmp_path.as_posix(), "&&", "exec", *child]


@pytest.mark.parametrize("graphical", [False, True])
def test_linux_without_terminal_support_explains_manual_fallback(monkeypatch, tmp_path, graphical):
    launcher = importlib.import_module("app.simulation.launcher")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    if graphical:
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(launcher.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="operator.*customer"):
        launcher.terminal_command([sys.executable], tmp_path, system="Linux")


def test_launcher_waits_for_real_operator_without_consuming_its_connection(monkeypatch, capsys):
    launcher = importlib.import_module("app.simulation.launcher")
    processes = []
    roles = []

    def open_terminal(command, cwd):
        role = command[3]
        roles.append(role)
        if role == "customer":
            assert command[command.index("--scenario") + 1] == "hitl_rejection"
            port = command[command.index("--port") + 1]
            ready_file = command[command.index("--ready-file") + 1]
            command = [sys.executable, "-c", (
                "import pathlib,socket,sys; "
                "from app.simulation.launcher import write_status; "
                "connection=socket.create_connection(('127.0.0.1',int(sys.argv[1]))); "
                "write_status(pathlib.Path(sys.argv[2]),'ready'); "
                "connection.sendall(b'{\"finished\":\"launcher-smoke\"}\\n'); connection.close()"
            ), port, ready_file]
        process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        processes.append(process)
        return process

    monkeypatch.setattr(launcher, "open_terminal", open_terminal)
    try:
        assert launcher.launch(port=0, scenario="hitl_rejection", startup_timeout=15) == 0
        assert roles == ["operator", "customer"]
        assert processes[1].communicate(timeout=10)[0] == ""
        assert processes[1].returncode == 0
        output = processes[0].communicate(timeout=10)[0]
        assert "Customer terminal connected" in output
        assert "Session ended: launcher-smoke" in output
        assert processes[0].returncode == 0
        assert "Opened both manual terminals" in capsys.readouterr().out
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate()


def test_busy_port_prevents_customer_launch(monkeypatch):
    launcher = importlib.import_module("app.simulation.launcher")
    processes = []

    def open_terminal(command, cwd):
        assert command[3] == "operator", "Customer must not start after a bind failure"
        process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        processes.append(process)
        return process

    monkeypatch.setattr(launcher, "open_terminal", open_terminal)
    with socket.create_server(("127.0.0.1", 0)) as occupied:
        try:
            with pytest.raises(RuntimeError, match="Operator startup failed"):
                launcher.launch(port=occupied.getsockname()[1], startup_timeout=15)
            assert len(processes) == 1
            assert processes[0].poll() is not None
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.communicate()


def test_both_real_consoles_reach_customer_prompt_without_model_input(monkeypatch):
    launcher = importlib.import_module("app.simulation.launcher")
    processes = []

    def open_terminal(command, cwd):
        process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        processes.append(process)
        return process

    monkeypatch.setattr(launcher, "open_terminal", open_terminal)
    try:
        assert launcher.launch(port=0, startup_timeout=15) == 0
        customer_output = processes[1].communicate(input="", timeout=10)[0]
        operator_output = processes[0].communicate(input="", timeout=10)[0]
        assert "Agent A | Travel planner" in customer_output
        assert "Customer:" in customer_output
        assert "Customer terminal connected" in operator_output
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)


def test_one_command_real_mode_starts_backend_and_both_human_consoles(monkeypatch):
    import httpx
    launcher = importlib.import_module('app.simulation.launcher')
    processes = []
    with socket.create_server(('127.0.0.1', 0)) as listener:
        backend_port = listener.getsockname()[1]
    url = f'http://127.0.0.1:{backend_port}'
    monkeypatch.setenv('OPERATOR_URL', url)

    def open_terminal(command, cwd):
        child = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        processes.append(child)
        return child

    monkeypatch.setattr(launcher, 'open_terminal', open_terminal)
    try:
        assert launcher.launch(port=0, mode='real', startup_timeout=15) == 0
        assert len(processes) == 2
        assert httpx.get(url + '/health', trust_env=False).json() == {'service': 'picos-operator-demo'}
        customer_output = processes[1].communicate(input='', timeout=10)[0]
        operator_output = processes[0].communicate(input='', timeout=10)[0]
        assert 'real services' in customer_output
        assert 'Customer terminal connected' in operator_output
        with pytest.raises(httpx.TransportError):
            httpx.get(url + '/health', timeout=0.2, trust_env=False)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)


def test_startup_timeout_stops_operator_and_does_not_launch_customer(monkeypatch):
    launcher = importlib.import_module("app.simulation.launcher")
    processes = []

    def open_terminal(command, cwd):
        assert command[3] == "operator"
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], cwd=cwd)
        processes.append(process)
        return process

    monkeypatch.setattr(launcher, "open_terminal", open_terminal)
    try:
        with pytest.raises(RuntimeError, match="Timed out"):
            launcher.launch(startup_timeout=0.1)
        assert len(processes) == 1
        assert processes[0].poll() is not None
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait()


def test_customer_launch_failure_stops_ready_operator(monkeypatch):
    launcher = importlib.import_module("app.simulation.launcher")
    processes = []

    def open_terminal(command, cwd):
        if command[3] == "customer":
            raise OSError("Customer terminal could not open")
        process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        processes.append(process)
        return process

    monkeypatch.setattr(launcher, "open_terminal", open_terminal)
    try:
        with pytest.raises(OSError, match="Customer terminal could not open"):
            launcher.launch(port=0, startup_timeout=15)
        assert processes[0].poll() is not None
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate()


def test_customer_process_failure_is_reported_and_stops_operator(monkeypatch):
    launcher = importlib.import_module("app.simulation.launcher")
    processes = []

    def open_terminal(command, cwd):
        if command[3] == "customer":
            command = [sys.executable, "-c", "raise SystemExit(7)"]
        process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        processes.append(process)
        return process

    monkeypatch.setattr(launcher, "open_terminal", open_terminal)
    try:
        with pytest.raises(RuntimeError, match="Customer terminal exited with code 7"):
            launcher.launch(port=0, startup_timeout=15)
        assert len(processes) == 2
        assert processes[0].poll() is not None
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate()


def test_detached_console_queued_after_timeout_exits_without_starting_session(monkeypatch):
    launcher = importlib.import_module("app.simulation.launcher")
    queued = []

    def open_terminal(command, cwd):
        child = subprocess.Popen([
            sys.executable, "-c",
            "import runpy,sys,time; time.sleep(0.4); "
            "module=sys.argv[1]; sys.argv=sys.argv[1:]; runpy.run_module(module,run_name='__main__')",
            command[2], *command[3:],
        ], cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        queued.append(child)
        return subprocess.Popen([sys.executable, "-c", "pass"], cwd=cwd)

    monkeypatch.setattr(launcher, "open_terminal", open_terminal)
    try:
        with pytest.raises(RuntimeError, match="Timed out"):
            launcher.launch(port=0, startup_timeout=0.1)
        output = queued[0].communicate(timeout=5)[0]
        assert queued[0].returncode == 0, output
        assert "Listening" not in output
        assert "Press Enter" not in output
    finally:
        for process in queued:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)


def test_console_publishes_pid_before_import_and_honors_cancellation(monkeypatch, tmp_path):
    bootstrap = importlib.import_module("app.simulation.manual_bootstrap")
    status_file = tmp_path / "operator.json"
    monkeypatch.setattr(sys, "argv", ["bootstrap", "operator", "--ready-file", str(status_file)])

    def import_manual(name):
        assert name == "app.simulation.manual"
        status = json.loads(status_file.read_text(encoding="utf-8"))
        assert status["state"] == "starting"
        assert status["pid"] > 0
        (tmp_path / "cancelled").touch()
        return SimpleNamespace(main=lambda: pytest.fail("Cancelled startup must not enter the console"))

    monkeypatch.setattr(bootstrap.importlib, "import_module", import_manual)
    assert bootstrap.main() == 0

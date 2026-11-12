import asyncio
import json
import subprocess
import sys

from test_integration import ScriptedModel

from app.simulation import manual


def test_manager_rejects_with_reason():
    replies = iter(["reject", "Use a poncho"])
    answer = manual.manager_answer(
        {"kind": "approval", "question": "Approve?", "proposal": {"guide_id": "luis"}},
        read=lambda _: next(replies),
        show=lambda _: None,
    )
    assert answer == "Rejected. Use a poncho"


def test_two_consoles_complete_one_booking(monkeypatch, tmp_path, capsys):
    operator = subprocess.Popen(
        [sys.executable, "-m", "app.simulation.manual", "operator", "--port", "0"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        port = int(operator.stdout.readline().strip().rsplit(":", 1)[1])
        operator.stdin.write("9\n2\nmaybe\napprove\n")
        operator.stdin.flush()
        monkeypatch.chdir(tmp_path)
        replies = iter(["", "I have boots, water and a first aid kit."])
        monkeypatch.setattr("builtins.input", lambda _: next(replies))
        monkeypatch.setattr("app.simulation.runner.load_model", ScriptedModel)
        assert asyncio.run(manual.customer_console(port, "happy_path")) == 0
        output = operator.communicate(timeout=10)[0]
        assert "2. luis" in output and "Session ended: confirmed" in output
        assert "Enter approve or reject." in output
        assert "Reservation TR-" in capsys.readouterr().out
        directory = tmp_path / "trajectories/manual"
        path, = directory.glob("*.json")
        assert list(directory.iterdir()) == [path]
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["result"]["status"] == "confirmed"
        assert doc["result"]["trip_result"]["status"] == "confirmed"
        assert doc["result"]["error"] is None
        assert not {"passed", "checks", "metrics"} & doc["result"].keys()
        assert doc["events"][-1]["type"] == "simulation.completed"
    finally:
        if operator.poll() is None:
            operator.kill()
        operator.wait()

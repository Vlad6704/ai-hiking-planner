import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(UTC).isoformat()


def redact(value):
    if isinstance(value, dict):
        return {
            key: "[redacted]"
            if re.search(r"authorization|password|api[_-]?key|access_token", key, re.IGNORECASE)
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return re.sub(
            r"[\w.+-]+@[\w.-]+\.\w+|Bearer\s+\S+", "[redacted]", value, flags=re.IGNORECASE
        )[:8192]
    return value


class TraceRecorder:
    def __init__(self, metadata, max_steps=None):
        self.max_steps = max_steps
        self.metadata = dict(schema_version="1", started_at=now(), **metadata)
        self.started = time.monotonic()
        self.events = []

    def emit(
        self, kind, actor, data, *, recipient=None, caused_by=None, operation_id=None
    ):
        terminal = kind in ("simulation.completed", "simulation.failed")
        if self.max_steps is not None and len(self.events) >= self.max_steps - int(not terminal):
            raise RuntimeError("step_limit")
        event = dict(
            event_id=str(uuid4()),
            seq=len(self.events) + 1,
            timestamp=now(),
            type=kind,
            actor=actor,
            recipient=recipient,
            caused_by=caused_by,
            operation_id=operation_id,
            data=data,
        )
        self.events.append(event)
        return event

    def write(self, directory: Path, result):
        self.metadata.update(
            finished_at=now(),
            duration_ms=round((time.monotonic() - self.started) * 1000),
        )
        path = (
            directory
            / self.metadata["scenario_id"]
            / (self.metadata["run_id"] + ".json")
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        document = redact(
            dict(metadata=self.metadata, events=self.events, result=result)
        )
        temp.write_text(
            json.dumps(document, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        temp.replace(path)
        return path

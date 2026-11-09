import asyncio
import time
import sqlite3
from uuid import uuid4

import httpx
from pydantic import TypeAdapter

from app.models.contracts import ToolResult


async def execute(name, arguments, call, settings, trace, actor, fallback=None, metadata=None):
    operation = str(uuid4())

    def emit(kind, **data):
        return trace.emit(
            kind,
            actor,
            dict(tool=name, tool_call_id=operation, **data),
            operation_id=operation,
        )

    for attempt in range(1, settings.attempts + 1):
        start = time.monotonic()
        emit("tool.called", arguments=arguments, mode=settings.mode, attempt=attempt)
        try:
            async with asyncio.timeout(settings.tool_timeout):
                data = await call()
            normalized = TypeAdapter(object).dump_python(data, mode="json")
            status = "degraded" if metadata and metadata.get("catalog", {}).get("stale") else "success"
            result = ToolResult(
                status=status, data=normalized, source=name, mode=settings.mode, metadata=metadata
            )
            emit(
                "tool.completed",
                output=result.model_dump(),
                status=status,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            return result.model_dump()
        except (ValueError, KeyError, IndexError, TimeoutError, httpx.HTTPError, sqlite3.Error) as exc:
            retry = isinstance(exc, (TimeoutError, httpx.TransportError)) or (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code in (429, 503)
            )
            code = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            emit("tool.failed", error_code=code, retryable=retry, attempt=attempt)
            if retry and attempt < settings.attempts:
                emit("tool.retry", attempt=attempt + 1)
                await asyncio.sleep(0.5 * 2 ** (attempt - 1))
                continue
            if retry and fallback:
                emit("recovery.started", failed_operation=operation)
                try:
                    data = TypeAdapter(object).dump_python(fallback(), mode="json")
                except ValueError as invalid:
                    code = str(invalid)
                    emit("recovery.failed", reason=code)
                else:
                    emit(
                        "recovery.applied",
                        failed_operation=operation,
                        strategy="approved_snapshot",
                        outcome=data,
                    )
                    return ToolResult(
                        status="degraded",
                        data=data,
                        source="approved_snapshot",
                        mode=settings.mode,
                    ).model_dump()
            return ToolResult(
                status="error",
                mode=settings.mode,
                source=name,
                error=dict(code=code, message=code, retryable=retry),
            ).model_dump()

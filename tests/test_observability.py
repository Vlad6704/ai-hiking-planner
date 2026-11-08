from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.observability.langsmith import Usage


def test_token_counts():
    usage = Usage()
    usage.on_llm_end(
        LLMResult(
            generations=[
                [
                    ChatGeneration(
                        message=AIMessage(
                            content="yes",
                            usage_metadata={
                                "input_tokens": 5,
                                "output_tokens": 2,
                                "total_tokens": 7,
                            },
                        )
                    )
                ]
            ]
        )
    )
    assert usage.calls == 1 and usage.input_tokens == 5 and usage.output_tokens == 2


def test_enabled_trace_redacts_and_closes(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    import app.observability.langsmith as tracing
    from app.observability.trace import TraceRecorder

    closed, emitted = [], []
    client = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setattr(tracing, "Client", lambda **kwargs: client)
    monkeypatch.setattr(tracing, "tracing_context", lambda **kwargs: nullcontext())
    root = SimpleNamespace(trace_id="remote-id", add_event=emitted.append)
    monkeypatch.setattr(tracing, "trace", lambda *args, **kwargs: nullcontext(root))
    recorder = TraceRecorder({"request_id": "request"})
    with tracing.session(recorder):
        recorder.emit("simulation.started", "runner", {"api_key": "private-key"})
    assert closed and recorder.metadata["langsmith_trace_id"] == "remote-id"
    assert "private-key" not in str(emitted)

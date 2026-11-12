from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.observability.langsmith import Usage
import pytest


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


def test_usage_counts_multi_tool_responses():
    usage = Usage()
    message = AIMessage(content="", tool_calls=[
        dict(name="check_guide_availability", args={}, id="guides"),
        dict(name="check_equipment_inventory", args={}, id="stock"),
    ])
    usage.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]))
    assert usage.calls == 1
    assert usage.parallel_tool_batches == 1
    usage.on_llm_end(LLMResult(generations=[[
        ChatGeneration(message=message), ChatGeneration(message=message)
    ]]))
    assert usage.calls == 2
    assert usage.parallel_tool_batches == 2


def record_usage(counter, details):
    metadata = dict(input_tokens=100, output_tokens=5, total_tokens=105)
    if details is not None:
        metadata["input_token_details"] = details
    counter.on_llm_end(LLMResult(generations=[[
        ChatGeneration(message=AIMessage(content="done", usage_metadata=metadata))
    ]]))


@pytest.mark.parametrize("details, expected_read, expected_write", [
    (None, None, None),
    ({"cache_read": 0}, 0, None),
    ({"cache_read": 60, "cache_creation": 20}, 60, 20),
    ({"priority_cache_read": 40, "priority_cache_creation": 30}, 40, 30),
    ({"flex_cache_read": 50}, 50, None),
])
def test_cache_usage_preserves_missing_zero_and_service_tiers(details, expected_read, expected_write):
    counter = Usage()
    record_usage(counter, details)
    summary = counter.cache_metrics()
    assert summary["cached_input_tokens"] == expected_read
    assert summary["cache_write_tokens"] == expected_write
    assert summary["cache_read_ratio"] == (expected_read / 100 if expected_read is not None else None)
    assert counter.input_tokens == 100


def test_partial_cache_reporting_does_not_claim_complete_total():
    counter = Usage()
    record_usage(counter, {"cache_read": 60, "cache_creation": 20})
    record_usage(counter, None)
    summary = counter.cache_metrics()
    assert summary["cached_input_tokens"] is None
    assert summary["cache_write_tokens"] is None
    assert summary["cache_read_ratio"] is None
    assert summary["cache_read_reported_calls"] == 1


def test_cache_totals_require_both_active_agents_to_report():
    from app.evaluation.checks import cache_totals
    a, b = Usage(), Usage()
    record_usage(a, {"cache_read": 60, "cache_creation": 20})
    record_usage(b, {"cache_read": 40, "cache_creation": 30})
    def summaries():
        return {name: dict(llm_call_count=u.calls, input_tokens=u.input_tokens, **u.cache_metrics())
                for name, u in [("a", a), ("b", b)]}
    total = cache_totals(summaries())
    assert total["cached_input_tokens"] == 100
    assert total["cache_write_tokens"] == 50
    assert total["cache_read_ratio"] == 0.5
    record_usage(b, None)
    assert cache_totals(summaries())["cached_input_tokens"] is None

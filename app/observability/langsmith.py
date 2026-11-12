import os
from contextlib import closing, contextmanager

from langchain_core.callbacks import BaseCallbackHandler
from langsmith import Client, trace, tracing_context

from app.observability.trace import redact


def cache_detail(details, name):
    value = details.get(name)
    if value is not None:
        return value
    values = [details[key] for key in ("priority_" + name, "flex_" + name)
              if details.get(key) is not None]
    return sum(values) if values else None


class Usage(BaseCallbackHandler):
    def __init__(self):
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.reported = 0
        self.parallel_tool_batches = 0
        self.cached_input_tokens = 0
        self.cache_write_tokens = 0
        self.cache_read_reported_calls = 0
        self.cache_write_reported_calls = 0

    def on_llm_end(self, response, **kwargs):
        self.calls += 1
        has_parallel_batch = False
        for group in response.generations:
            for generation in group:
                message = getattr(generation, "message", None)
                if len(getattr(message, "tool_calls", [])) > 1:
                    has_parallel_batch = True
                usage = getattr(
                    message, "usage_metadata", None
                )
                if usage:
                    self.reported += 1
                    self.input_tokens += usage["input_tokens"]
                    self.output_tokens += usage["output_tokens"]
                    details = usage.get("input_token_details") or {}
                    cached = cache_detail(details, "cache_read")
                    written = cache_detail(details, "cache_creation")
                    if cached is not None:
                        self.cached_input_tokens += cached
                        self.cache_read_reported_calls += 1
                    if written is not None:
                        self.cache_write_tokens += written
                        self.cache_write_reported_calls += 1
        self.parallel_tool_batches += int(has_parallel_batch)

    def cache_metrics(self):
        cached = self.cached_input_tokens if self.calls and self.cache_read_reported_calls == self.calls else None
        written = self.cache_write_tokens if self.calls and self.cache_write_reported_calls == self.calls else None
        return dict(
            cached_input_tokens=cached,
            cache_write_tokens=written,
            cache_read_ratio=cached / self.input_tokens if cached is not None and self.input_tokens else None,
            cache_read_reported_calls=self.cache_read_reported_calls,
            cache_write_reported_calls=self.cache_write_reported_calls,
        )


@contextmanager
def session(recorder):
    enabled = os.getenv("LANGSMITH_TRACING", "").lower() == "true"
    if not enabled:
        with tracing_context(enabled=False):
            yield
        return
    with (
        closing(
            Client(hide_inputs=redact, hide_outputs=redact, hide_metadata=redact)
        ) as client,
        tracing_context(enabled=True, client=client),
        trace(
            "hiking-simulation",
            inputs={"request_id": recorder.metadata["request_id"]},
        ) as root,
    ):
        recorder.metadata["langsmith_trace_id"] = str(root.trace_id)
        yield
        for event in recorder.events:
            root.add_event(
                {
                    "name": event["type"],
                    "time": event["timestamp"],
                    "kwargs": redact(event),
                }
            )

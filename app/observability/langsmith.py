import os
from contextlib import contextmanager

from langchain_core.callbacks import BaseCallbackHandler
from langsmith import Client, trace, tracing_context

from app.observability.trace import redact


class Usage(BaseCallbackHandler):
    def __init__(self):
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.reported = 0

    def on_llm_end(self, response, **kwargs):
        self.calls += 1
        for group in response.generations:
            for generation in group:
                usage = getattr(
                    getattr(generation, "message", None), "usage_metadata", None
                )
                if usage:
                    self.reported += 1
                    self.input_tokens += usage["input_tokens"]
                    self.output_tokens += usage["output_tokens"]


@contextmanager
def session(recorder):
    enabled = os.getenv("LANGSMITH_TRACING", "").lower() == "true"
    if not enabled:
        with tracing_context(enabled=False):
            yield
        return
    with (
        Client(hide_inputs=redact, hide_outputs=redact, hide_metadata=redact) as client,
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

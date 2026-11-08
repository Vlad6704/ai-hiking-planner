import asyncio
import time
from uuid import uuid4

from app.observability.trace import now

PEER = {"agent_a": "agent_b", "agent_b": "agent_a"}


class MessageBus:
    def __init__(self, request_id, trace, timeout, limit):
        self.request_id = request_id
        self.trace = trace
        self.timeout = timeout
        self.limit = limit
        self.count = 0
        self.pending = {}
        self.replies = {}
        self.seen = set()
        self.queues = {agent: asyncio.Queue() for agent in PEER}

    def send(self, sender, content, kind, parent=None):
        recipient = PEER[sender]
        if self.count >= self.limit:
            raise ValueError("exchange_limit")
        key = None
        if kind in ("response", "error"):
            key = (parent or {}).get("message_id")
            original, deadline = self.pending.get(key, ({}, 0))
            if (
                original != parent
                or key in self.replies
                or deadline <= time.monotonic()
                or original.get("recipient") != sender
            ):
                raise ValueError("invalid_correlation")
        elif kind not in ("request", "notification"):
            raise ValueError("invalid_message_kind")
        message = dict(
            message_id=str(uuid4()),
            request_id=self.request_id,
            sender=sender,
            recipient=recipient,
            correlation_id=key,
            type=kind,
            content=content,
            timestamp=now(),
        )
        event = self.trace.emit(
            "agent.message_sent",
            sender,
            dict(**message, destination=recipient),
            recipient=recipient,
            operation_id=key or message["message_id"],
        )
        if key:
            self.replies[key] = message["message_id"]
        if kind == "request":
            self.pending[message["message_id"]] = (
                message,
                time.monotonic() + self.timeout,
            )
        self.queues[recipient].put_nowait((message, event["event_id"]))
        self.count += 1
        return message

    async def receive(self, agent_id):
        while True:
            message, parent = await self.queues[agent_id].get()
            key = message["message_id"]
            correlation = message.get("correlation_id")
            if (
                key in self.seen
                or message["request_id"] != self.request_id
                or message["recipient"] != agent_id
                or message["sender"] != PEER[agent_id]
            ):
                continue
            if message["type"] in ("response", "error"):
                original, deadline = self.pending.get(correlation, ({}, 0))
                if (
                    self.replies.get(correlation) != key
                    or original.get("sender") != agent_id
                ):
                    continue
                self.replies.pop(correlation)
                self.pending.pop(correlation)
                if time.monotonic() >= deadline:
                    self.trace.emit(
                        "agent.message_expired", agent_id, {"message_id": key}
                    )
                    continue
            self.seen.add(key)
            self.trace.emit(
                "agent.message_received",
                agent_id,
                message,
                caused_by=parent,
                operation_id=message["correlation_id"] or key,
            )
            return message

import asyncio
import os
import time
from uuid import uuid4

import httpx
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.factory import build_agent, load_model
from app.agents.tools import bind_tools
from app.humans.approval import ApprovalRegistry
from app.humans.simulator import HumanSimulator
from app.messaging.bus import MessageBus
from app.models.contracts import Forecast
from app.observability.langsmith import Usage, session
from app.observability.trace import TraceRecorder
from app.tools.adapters.operator_http import HttpOperatorProvider
from app.tools.operator import MockOperator, OperatorTools


async def deliver_final(result, text, human, trace):
    equipment = ", ".join(sorted(result.equipment_items)) or "none"
    expected = (
        f"Confirmed {result.route_id} on {result.date} with {result.guide_id}. "
        f"Reservation {result.reservation_id}. Equipment: {equipment}."
    )
    if text != (expected if result.status == "confirmed" else result.failure_reason):
        raise ValueError(
            f"Use the exact final message: {expected if result.status == 'confirmed' else result.failure_reason}"
        )
    mid = str(uuid4())
    parent = trace.emit("result.validated", "agent_a", {}, operation_id=mid)
    await human.deliver("agent_a", mid, text)
    delivery = trace.emit(
        "human.message_delivered",
        "agent_a",
        dict(
            message_id=mid,
            text=text,
            message_kind="final_result",
            trip_result=result.model_dump(mode="json"),
        ),
        recipient="human_a",
        caused_by=parent["event_id"],
        operation_id=mid,
    )
    trace.emit("simulation.completed", "runner", {}, caused_by=delivery["event_id"])


class SimulationRunner:
    def __init__(self, case, settings, seed, model=None):
        self.case = case
        self.settings = settings
        self.model = model
        self.rid = str(uuid4())
        self.trace = TraceRecorder(
            dict(
                run_id=str(uuid4()),
                request_id=self.rid,
                scenario_id=case["id"],
                seed=seed,
                model=os.getenv("HIKING_MODEL", "ollama:gemma4:26b"),
                environment_mode=settings.mode,
                langsmith_trace_id=None,
            ),
            max_steps=settings.steps,
        )
        self.bus = MessageBus(
            self.rid, self.trace, settings.peer_timeout, settings.exchanges
        )
        self.humans = {a: HumanSimulator(case["rules"]) for a in ("agent_a", "agent_b")}
        self.approvals = ApprovalRegistry()
        self.forecast = Forecast.model_validate(case["weather"])
        self.incoming = {}
        self.observed = {}
        self.active = set()
        self.result = None
        self.error = None
        self.selected = None
        self.decisions = list(case["decisions"])
        self.done = asyncio.Event()
        self.usage = {actor: Usage() for actor in self.humans}

    def human_reply(self, actor, item):
        data = item.value
        recipient = actor.replace("agent", "human")
        event = self.trace.emit(
            "human.interrupt",
            actor,
            dict(**data, interaction_id=item.id),
            recipient=recipient,
            operation_id=item.id,
        )
        reply = dict(
            matched_intent=[data["kind"]], match_score=1, interaction_id=item.id
        )
        if actor == "agent_b" and data["kind"] == "selection":
            options = data["options"]
            available = {
                g["guide_id"]
                for group in self.observed.get("check_guide_availability", [])
                for g in group
            }
            if not options or not set(options) <= available:
                return {"error": "Present observed available guide IDs"}
            answer = str(self.case["choice"])
            self.selected = self.approvals.select(answer, options)
            reply.update(text=answer, guide_id=self.selected)
        elif actor == "agent_b" and data["kind"] == "approval":
            terms = data["proposal"]
            if not terms or not self.selected or terms["guide_id"] != self.selected:
                return {"error": "Select a guide and present exact terms first"}
            answer = (
                self.decisions.pop(0) if len(self.decisions) > 1 else self.decisions[0]
            )
            ref = self.approvals.record(self.rid, terms, answer)
            reply.update(text=answer, approval_ref=ref, proposal=terms)
        else:
            reply.update(self.humans[actor].answer(data["question"]))
        self.trace.emit(
            "human.response",
            recipient,
            reply,
            recipient=actor,
            operation_id=item.id,
            caused_by=event["event_id"],
        )
        return reply

    async def finalize(self, result, text):
        if self.result or self.bus.pending or str(result.request_id) != self.rid:
            raise ValueError("Outstanding work or invalid request ID")
        booking = self.operator.result
        if booking or result.status == "confirmed":
            if (
                not booking
                or result.status != "confirmed"
                or any(
                    getattr(result, k) != getattr(booking, k)
                    for k in ("date", "route_id", "guide_id", "reservation_id")
                )
                or sorted(result.equipment_items) != sorted(booking.equipment)
            ):
                raise ValueError("Result disagrees with booking")
        if len(self.trace.events) + 3 > self.settings.steps:
            raise ValueError("step_limit")
        await deliver_final(result, text, self.humans["agent_a"], self.trace)
        self.result = result
        self.done.set()

    async def worker(self, actor, graph):
        initial = actor == "agent_a"
        config = {
            "configurable": {"thread_id": f"{self.rid}:{actor}"},
            "recursion_limit": self.settings.steps,
        }
        config["callbacks"] = [self.usage[actor]]
        while not self.done.is_set():
            if initial:
                content = self.case["initial"]
                self.trace.emit(
                    "human.message", "human_a", {"text": content}, recipient=actor
                )
                initial = False
            else:
                envelope = await self.bus.receive(actor)
                self.incoming[actor] = envelope
                content = envelope["content"]
            self.active.add(actor)
            try:
                args = {
                    "messages": [("user", f"Request ID {self.rid}. {content}")],
                    "request_id": self.rid,
                }
                first_event = len(self.trace.events)
                reminded = False
                while True:
                    state = await graph.ainvoke(args, config)
                    interrupts = state.get("__interrupt__", [])
                    if not interrupts:
                        if not self.done.is_set():
                            self.trace.emit("agent.turn_finished", actor, {"text":state["messages"][-1].content})
                            sent = any(e["type"] == "agent.message_sent" and e["actor"] == actor
                                       for e in self.trace.events[first_event:])
                            if not sent and not reminded:
                                reminded = True
                                args = {"messages":[("user","Runtime: plain assistant text stays private. "
                                        "Use the appropriate tool to contact your human, contact your peer, "
                                        "or deliver the verified final result. No message was delivered this turn.")]}
                                continue
                        break
                    answers = {i.id: self.human_reply(actor, i) for i in interrupts}
                    args = Command(resume=answers)
            finally:
                self.active.discard(actor)

    async def run(self):
        with session(self.trace):
            return await self._run()

    async def _run(self):
        self.trace.emit("simulation.started", "runner", {})
        jobs = []
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.tool_timeout
            ) as self.client:
                self.provider = (
                    MockOperator(self.case["guides"], self.case["stock"], ["PR-PNPE-2"])
                    if self.settings.mode == "mock"
                    else HttpOperatorProvider(os.getenv("OPERATOR_URL"), self.client)
                )
                self.operator = OperatorTools(self.rid, self.approvals, self.provider)
                model = self.model or load_model()
                for actor in self.bus.queues:
                    graph = build_agent(
                        actor, bind_tools(self, actor), model, InMemorySaver()
                    )
                    jobs.append(asyncio.create_task(self.worker(actor, graph)))
                try:
                    async with asyncio.timeout(self.settings.timeout):
                        while not self.done.is_set():
                            await asyncio.sleep(0.02)
                            if self.done.is_set():
                                break
                            for task in jobs:
                                if task.done():
                                    task.result()
                            if len(self.trace.events) >= self.settings.steps - 1:
                                raise ValueError("step_limit")
                            if any(
                                t <= time.monotonic()
                                for _, t in self.bus.pending.values()
                            ):
                                raise ValueError("peer_timeout")
                            if (
                                not self.active
                                and not self.bus.pending
                                and all(q.empty() for q in self.bus.queues.values())
                            ):
                                raise ValueError("deadlock")
                finally:
                    for task in jobs:
                        task.cancel()
                    await asyncio.gather(*jobs, return_exceptions=True)
        except Exception as exc:
            self.error = str(exc) or type(exc).__name__
            self.trace.emit(
                "simulation.failed",
                "runner",
                {"reason": self.error, "delivered": False},
            )
        return self

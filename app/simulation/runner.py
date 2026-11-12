import asyncio
import os
import logging
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime
from uuid import uuid4

import httpx
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.factory import build_agent, configured_model, load_model
from app.agents.tools import bind_tools
from app.agents.peer_facts import peer_model_content
from app.humans.simulator import HumanSimulator
from app.messaging.bus import MessageBus
from app.models.contracts import TripResult
from app.simulation.outcome import trip_message
from app.route_catalog.service import CatalogService
from app.route_catalog.seed import seed_store
from app.route_catalog.store import CatalogStore, database_path
from app.observability.langsmith import Usage, session
from app.observability.trace import TraceRecorder
from app.observability.asyncio_logging import capture_asyncio_errors
from app.observability.http_logging import attach_http_logging
from app.observability.runtime_logging import log_context
from app.time_context import TIMEZONE, planning_date
from app.tools.adapters.operator_http import HttpOperatorProvider
from app.tools.adapters.mock import FailureSchedule
from app.tools.operator import MockOperator


async def deliver_final(result, text, human, trace, *, complete=True):
    expected = trip_message(result)
    if text != expected:
        raise ValueError(f"Use the exact final message: {expected}")
    mid = str(uuid4())
    parent = trace.emit("result.validated", "agent_a", {}, operation_id=mid)
    try:
        await human.deliver("agent_a", mid, text)
    except Exception as exc:
        raise RuntimeError(f"delivery_failed: {exc}") from exc
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
    if complete:
        trace.emit("simulation.completed", "runner", {}, caused_by=delivery["event_id"])


class SimulationRunner:
    def __init__(self, case, settings, seed, model=None, *, checkpointers=None):
        self.case = case
        self.injection = FailureSchedule(case.get("failure_injection", {}), seed)
        self.settings = settings
        self.model = model
        self.checkpointers = checkpointers or {}
        self.rid = str(uuid4())
        self.current_date = planning_date(
            datetime.fromisoformat(case['clock']) if settings.mode == 'mock' else None
        )
        self.trace = TraceRecorder(
            dict(
                run_id=str(uuid4()),
                request_id=self.rid,
                scenario_id=case["id"],
                seed=seed,
                failure_injection=case.get('failure_injection', {}),
                weather_failure=case.get('weather_failure', False),
                fallback=case.get('fallback', False),
                model=configured_model(),
                environment_mode=settings.mode,
                current_date=self.current_date.isoformat(),
                timezone=TIMEZONE,
                settings=settings.model_dump(mode="json"),
                temperature=1 if configured_model() == "openai:gpt-6-luna" else
                            None if configured_model() == "openai:gpt-6-sol" else 0,
                langsmith_trace_id=None,
            ),
            max_steps=settings.steps,
        )
        self.bus = MessageBus(
            self.rid, self.trace, settings.peer_timeout, settings.exchanges
        )
        self.humans = {a: HumanSimulator(case["rules"], consent_terms=case.get("substitution_terms"))
                       for a in ("agent_a", "agent_b")}
        self.drivers = {}
        self.active = set()
        self.result = None
        self.final_delivery_attempted = False
        self.runtime_notification_attempted = False
        self.error = None
        self.decisions = list(case["decisions"])
        self.done = asyncio.Event()
        self.final_lock = asyncio.Lock()
        self.usage = {actor: Usage() for actor in self.humans}

    async def resolve_interrupt(self, actor, item):
        return self.human_reply(actor, item)

    def present_interrupt(self, actor, item):
        parent = next((e['event_id'] for e in reversed(self.trace.events)
                       if e['type'] == 'agent.message_received' and e['actor'] == actor
                       and e['data']['message_id'] == item.value.get('_source_message_id')), None)
        return self.trace.emit(
            'human.information' if item.value['kind'] == 'information' else 'human.interrupt',
            actor, dict(**item.value, interaction_id=item.id),
            recipient=actor.replace('agent', 'human'), operation_id=item.id, caused_by=parent,
        )

    def human_reply(self, actor, item, manual_answer=None, *, interrupt_event=None):
        data = item.value
        event = interrupt_event or self.present_interrupt(actor, item)
        reply = dict(interaction_id=item.id, interrupt_event_id=event['event_id'],
                     matched_intent=[data['kind']], match_score=1)
        if manual_answer is not None:
            reply.update(text=manual_answer, matched_intent=['manual'])
        elif actor == 'agent_b' and data['kind'] == 'selection':
            reply['text'] = str(self.case['choice'])
        elif actor == 'agent_b' and data['kind'] == 'approval':
            reply['text'] = self.decisions.pop(0) if len(self.decisions) > 1 else self.decisions[0]
        else:
            kwargs = dict(intent='substitution', proposal=data['proposal'], original_proposal=data.get('_original_proposal')) if data['kind'] == 'substitution' else {}
            reply.update(self.humans[actor].answer(data['question'], **kwargs))
        return reply

    async def _deliver_result(self, result):
        async with self.final_lock:
            if self.final_delivery_attempted:
                raise ValueError('Final delivery has already been attempted')
            self.final_delivery_attempted = True
            await deliver_final(result, trip_message(result), self.humans['agent_a'], self.trace, complete=False)

    async def notify_runtime_failure(self, reason):
        if self.runtime_notification_attempted:
            return
        self.runtime_notification_attempted = True
        self.error = reason
        self.trace.reserve_terminal_events()
        delivered = any(e['type'] == 'human.message_delivered' for e in self.trace.events)
        delivery_error = None
        if not delivered and not self.final_delivery_attempted:
            self.final_delivery_attempted = True
            driver = self.drivers.get('agent_a')
            if driver:
                while not self.bus.queues['agent_a'].empty():
                    try:
                        await driver.receive(await self.bus.receive('agent_a'))
                    except RuntimeError as exc:
                        if str(exc) != 'step_limit':
                            raise
                        break
                state = await driver.get_state()
            else:
                state = {}
            outcome = state.get('received_outcome') or {}
            receipt = outcome.get('reservation')
            pending = state.get('booking_progress')
            if receipt:
                result = TripResult(request_id=self.rid, status='confirmed',
                    route_id=receipt['route_id'], date=receipt['date'], guide_id=receipt['guide_id'],
                    equipment_items=list(receipt['equipment']), reservation_id=receipt['reservation_id'])
                text = trip_message(result)
            elif outcome.get('status') == 'uncertain' or pending or any(
                    message.get('type') == 'request' and message['message_id'] in self.bus.pending
                    for record in state.get('outbox', {}).values()
                    for message in [record.get('envelope', record)]):
                result = None
                text = "We couldn't confirm your booking status. Please contact the operator before trying again."
            else:
                result = TripResult(request_id=self.rid, status='failed', failure_reason=reason)
                text = trip_message(result)
            mid = str(uuid4())
            parent = self.trace.emit('runtime.notification_started', 'runner', {'reason': reason}, operation_id=mid)
            try:
                async with asyncio.timeout(5):
                    await self.humans['agent_a'].deliver('agent_a', mid, text)
            except Exception as exc:
                delivery_error = str(exc) or type(exc).__name__
            else:
                self.result = result
                if driver and result:
                    await driver.update({'result': result.model_dump(mode='json')})
                self.trace.emit('human.message_delivered', 'runner',
                    dict(message_id=mid, text=text, message_kind='final_result',
                         trip_result=result.model_dump(mode='json') if result else None),
                    recipient='human_a', caused_by=parent['event_id'], operation_id=mid)
                delivered = True
        self.trace.emit('simulation.failed', 'runner',
                        dict(reason=reason, delivered=delivered, delivery_error=delivery_error))
        self.done.set()

    async def worker(self, actor, driver):
        initial = actor == 'agent_a'
        while not self.done.is_set():
            if initial:
                content = self.case['initial']
                self.trace.emit('human.message', 'human_a', {'text': content}, recipient=actor)
                initial = False
            else:
                envelope = await self.bus.receive(actor)
                if not await driver.receive(envelope):
                    continue
                content = peer_model_content(envelope)
            self.active.add(actor)
            try:
                args = {'messages': [('user', f'Request ID {self.rid}. {content}')], 'request_id': self.rid}
                if actor == 'agent_a' and not (await driver.get_state()).get('requirements'):
                    args['requirements'] = {'initial_request': self.case['initial'], 'reply_references': {}}
                reminded = False
                while not self.done.is_set():
                    state = await driver.graph.ainvoke(args, driver.config)
                    await driver.flush_outbox()
                    saved = await driver.get_state()
                    if actor == 'agent_a' and saved.get('result'):
                        self.result = TripResult.model_validate(saved['result'])
                        delivery = next(e for e in reversed(self.trace.events) if e['type'] == 'human.message_delivered')
                        self.trace.emit('simulation.completed', 'runner', {}, caused_by=delivery['event_id'])
                        self.done.set()
                        break
                    interrupts = state.get('__interrupt__', [])
                    if interrupts:
                        replies = {item.id: await self.resolve_interrupt(actor, item) for item in interrupts}
                        args = Command(resume=replies)
                        continue
                    snapshot = await driver.graph.aget_state(driver.config)
                    last = saved['messages'][-1]
                    if getattr(last, 'name', '') in ('send_to_agent', 'reply_with_customer_decision', 'acknowledge_message'):
                        self.trace.emit('agent.turn_finished', actor, {'text': last.content})
                        break
                    if snapshot.next:
                        await driver.claim_booking_execution(driver.context)
                        args = None
                        continue
                    text = saved['messages'][-1].content
                    self.trace.emit('agent.turn_finished', actor, {'text': text})
                    # return_direct peer tools deliberately yield after dispatch.
                    last = saved['messages'][-1]
                    acted = getattr(last, 'name', '') in ('send_to_agent', 'reply_with_customer_decision', 'acknowledge_message')
                    if not acted and not reminded:
                        reminded = True
                        args = {'messages': [('user', 'Use a tool to reply to your peer, ask your human, or submit the final result. Plain text is not delivered.')]}
                        continue
                    break
            finally:
                self.active.discard(actor)

    async def run(self):
        with log_context(component='simulation', run_id=self.trace.metadata['run_id'], request_id=self.rid), capture_asyncio_errors('simulation'):
            logger = logging.getLogger('app.simulation')
            logger.info('simulation.started', extra={'fields': {'mode': self.settings.mode}})
            with session(self.trace):
                result = await self._run()
            logger.info('simulation.finished', extra={'fields': {'outcome': 'failed' if self.error else (self.result.status if self.result else 'incomplete')}})
            return result

    async def _run(self):
        self.trace.emit("simulation.started", "runner", {})
        jobs = []
        catalog_directory = None
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.tool_timeout
            ) as self.client:
                attach_http_logging(self.client)
                if self.settings.mode == 'mock':
                    catalog_directory = TemporaryDirectory(prefix='picos-routes-')
                    clock = lambda: self.case['clock']
                    store = CatalogStore(Path(catalog_directory.name) / 'routes.sqlite3', clock=clock)
                    self.trace.metadata['catalog_seed_id'] = seed_store(store, checked_at=clock())
                    self.catalog = CatalogService(store, self.client,
                        clock=lambda: datetime.fromisoformat(clock()), refresh_enabled=False)
                    supported_routes = [variant.variant_id for route in store.records().values() for variant in route.variants]
                else:
                    self.catalog = CatalogService(CatalogStore(database_path()), self.client)
                if self.settings.mode == 'mock':
                    if self.case.get('manual_preset') is not None:
                        from app.simulation.presets import ManualPreset, preset_operator
                        self.provider = preset_operator(ManualPreset.model_validate(self.case['manual_preset']), supported_routes)
                    else:
                        self.provider = MockOperator(self.case['guides'], self.case['stock'], supported_routes)
                else:
                    from app.simulation.presets import ManualPreset
                    preset = self.case.get('manual_preset')
                    self.provider = HttpOperatorProvider(os.getenv('OPERATOR_URL'), self.client,
                        preset=ManualPreset.model_validate(preset) if preset is not None else None)
                self.model = self.model or load_model()
                for actor in self.bus.queues:
                    from app.agents.context import AgentContext
                    from app.agents.driver import AgentDriver
                    context = AgentContext(actor, self.rid, self.settings, self.case, self.trace,
                        provider=self.provider if actor == 'agent_b' else None,
                        client=self.client, catalog=self.catalog if actor == 'agent_a' else None,
                        injection=self.injection, human=self.humans[actor],
                        deliver_final=self._deliver_result if actor == 'agent_a' else None)
                    saver = self.checkpointers.get(actor) or InMemorySaver()
                    graph = build_agent(actor, bind_tools(actor, context), self.model, saver,
                        current_date=self.current_date, agent_context=context)
                    config = {'configurable': {'thread_id': f'{self.rid}:{actor}'},
                              'recursion_limit': self.settings.steps, 'callbacks': [self.usage[actor]]}
                    driver = AgentDriver(graph, actor, config, self.bus)
                    driver.context = context
                    self.drivers[actor] = driver
                    jobs.append(asyncio.create_task(self.worker(actor, driver)))
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
            logging.getLogger('app.simulation').exception('simulation.failed')
            self.error = str(exc) or type(exc).__name__
            await self.notify_runtime_failure(self.error)
        finally:
            if catalog_directory is not None:
                catalog_directory.cleanup()
        return self

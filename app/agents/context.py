"""Role-local resources and scoped business updates for checkpointed tools."""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
from uuid import uuid4

import httpx

from app.models.contracts import BookingRequest, Forecast, Proposal, Reservation, TripResult
from app.models.messages import (
    AvailabilityResultPayload, CustomerDecisionPayload, OperationalFact, OperationalFailurePayload,
    PeerEnvelope, ReservationOutcomePayload, ReservationProgressPayload,
    TripOfferPayload, TripRequestPayload,
)
from app.observability.trace import now
from app.agents.peer_facts import selected_planning_facts


class AgentContext:
    """Runtime resources with business access limited to one active tool scope."""

    def __init__(self, actor, request_id, settings, case, trace, *, provider=None,
                 client=None, catalog=None, injection=None, human=None, deliver_final=None):
        self.actor = actor
        self.request_id = request_id
        self.rid = request_id
        self.settings = settings
        fixture_keys = ('clock', 'weather', 'weather_failure', 'fallback') if actor == 'agent_a' else ('clock',)
        self.case = {key: deepcopy(case[key]) for key in fixture_keys if key in case}
        self.trace = trace
        self.provider = provider if actor == 'agent_b' else None
        self.client = client
        self.catalog = catalog if actor == 'agent_a' else None
        self.injection = injection
        self.human = human
        self.deliver_final = deliver_final
        self.forecast = Forecast.model_validate(case['weather']) if actor == 'agent_a' else None
        self._scope = ContextVar(f'{request_id}:{actor}:tool-state')
        self._booking_permits = set()

    def grant_booking_execution(self, idempotency_key, tool_call_id):
        self._booking_permits.add((idempotency_key, tool_call_id))

    @contextmanager
    def activate(self, state):
        working = deepcopy(dict(state))
        token = self._scope.set(working)
        try:
            yield working
        finally:
            self._scope.reset(token)

    @property
    def state(self):
        try:
            return self._scope.get()
        except LookupError as exc:
            raise RuntimeError('Agent business state requires an active tool scope') from exc

    @staticmethod
    def changes(before, working):
        updates = {}
        keyed = {'observations', 'inbox', 'outbox', 'interactions', 'planning_facts', 'dispatch_ack'}
        for key, value in working.items():
            if key == 'messages' or key.startswith('_') or before.get(key) == value:
                continue
            if key in keyed:
                updates[key] = {item: deepcopy(record) for item, record in value.items()
                                if (before.get(key) or {}).get(item) != record}
            else:
                updates[key] = deepcopy(value)
        return updates

    @property
    def incoming(self):
        return self.state.get('incoming')

    @property
    def observed(self):
        records = [*self.state.get('planning_facts', {}).values(), *self.state.get('observations', {}).values()]
        result = {}
        for record in records:
            output = record['result']
            if output['status'] != 'error':
                result.setdefault(record['tool'], []).append(deepcopy(output['data']))
        return result

    def record_observation(self, tool, query, result, callid=None):
        callid = callid or self.state['_tool_call_id']
        self.state.setdefault('observations', {})[callid] = dict(
            tool=tool, query=deepcopy(query), result=deepcopy(result))

    def require_equipment(self, terms):
        records = [r for r in self.state.get('observations', {}).values()
                   if r['tool'] == 'check_equipment_inventory' and r['result']['status'] != 'error'
                   and r['query']['date'] == terms['date']]
        for item, quantity in terms['equipment'].items():
            latest = next((r['result']['data'] for r in reversed(records) if item in r['query']['items']), None)
            if latest is None or item in latest['unavailable'] or latest['quantities'].get(item, 0) < quantity:
                raise ValueError('verified_equipment_required')

    def needs_customer_consent(self, terms):
        original = self.state.get('original_proposal')
        changed = lambda prior: any(prior[k] != terms[k] for k in ('route_id', 'date', 'equipment'))
        return bool(self.state.get('offer') or original and changed(original)
                    or any(changed(rejected) for rejected in self.state.get('rejections', [])))

    def validate_manager_proposal(self, terms):
        if self.actor != 'agent_b':
            raise ValueError('manager_decisions_belong_to_operator')
        terms = Proposal.model_validate(terms).model_dump(mode='json')
        if not self.state.get('original_proposal'):
            raise ValueError('original_proposal_required')
        self.require_equipment(terms)
        if self.needs_customer_consent(terms):
            decision = self.state.get('customer_decision')
            if not decision or decision.get('decision') != 'accepted' or decision.get('proposal') != terms:
                raise ValueError('customer_consent_required')
            offer = self.state.get('offer')
            if offer and decision.get('offer_message_id') != offer['message_id']:
                raise ValueError('customer_consent_required')

    @property
    def has_pending_request(self):
        replied = {message.get('correlation_id') for message in self.state.get('inbox', {}).values()}
        return any(message['type'] == 'request' and message['message_id'] not in replied
                   for message in self.outgoing_messages)

    @property
    def outgoing_messages(self):
        return [record.get('envelope', record) for record in self.state.get('outbox', {}).values()]

    def _envelope(self, content, kind, payload, *, correlate=True):
        parent = self.incoming
        correlation = None
        if correlate and parent and parent.get('type') == 'request' and parent['message_id'] not in {
            m.get('correlation_id') for m in self.outgoing_messages
        }:
            kind = 'error' if kind == 'error' else 'response'
            correlation = parent['message_id']
        elif kind in ('response', 'error'):
            raise ValueError('No outstanding request to answer')
        message = PeerEnvelope(message_id=str(uuid4()), request_id=self.request_id,
            sender=self.actor, recipient='agent_b' if self.actor == 'agent_a' else 'agent_a',
            correlation_id=correlation, type=kind, content=content, timestamp=now(), payload=payload)
        record = message.model_dump(mode='json')
        self.state.setdefault('outbox', {})[message.message_id] = record
        return record

    def stage_message(self, content, kind='notification', proposal=None, *, payload=None):
        terms = proposal.model_dump(mode='json') if hasattr(proposal, 'model_dump') else proposal
        if payload is None and self.actor == 'agent_a' and terms is not None:
            facts = selected_planning_facts(self.state, terms)
            payload = TripRequestPayload(terms=terms, planning_facts=facts)
            if self.state.get('original_proposal') is None:
                self.state['original_proposal'] = deepcopy(terms)
        elif payload is None and self.actor == 'agent_b':
            booking = self.state.get('booking')
            if booking:
                payload = self.reservation_outcome()
                if not self.incoming or self.incoming.get('type') != 'request':
                    kind = 'notification'
            elif terms is not None:
                terms = Proposal.model_validate(terms).model_dump(mode='json')
                self.require_equipment(terms)
                if terms['guide_id'] != self.state.get('selected_guide'):
                    raise ValueError('A substitution offer requires manager-selected guide_id')
                payload = TripOfferPayload(proposal=terms)
            else:
                payload = AvailabilityResultPayload(reason=content, observations=[
                    OperationalFact(id=key, **record)
                    for key, record in self.state.get('observations', {}).items()
                    if record['tool'] in ('check_guide_availability', 'check_equipment_inventory')])
        elif payload is None and kind == 'error':
            payload = OperationalFailurePayload(code='operational_failure', reason=content)
        if self.actor == 'agent_a' and self.state.get('original_proposal') is None and payload is None and kind == 'request':
            raise ValueError('original_proposal_required')
        message = self._envelope(content, kind, payload)
        if isinstance(payload, TripOfferPayload):
            self.state['offer'] = dict(proposal=payload.proposal.model_dump(mode='json'), message_id=message['message_id'])
            self.state['approval'] = None
        return {'queued': message['message_id']}

    def process_human_reply(self, data, reply):
        reply = deepcopy(reply)
        self.state['pending_interaction'] = None
        self.state['trip_status'] = 'working'
        previous = self.state.get('interactions', {}).get(reply['interaction_id'])
        if previous:
            return deepcopy(previous)
        if self.actor == 'agent_b' and data['kind'] == 'selection':
            options = data['options']
            available = {g['guide_id'] for group in self.observed.get('check_guide_availability', []) for g in group}
            text = reply['text'].strip()
            if not options or not set(options) <= available or not text.isdigit() or not 1 <= int(text) <= len(options):
                raise ValueError('invalid_guide_choice')
            self.state['selected_guide'] = options[int(text) - 1]
            self.state['approval'] = None
            reply['guide_id'] = self.state['selected_guide']
        elif self.actor == 'agent_b' and data['kind'] == 'approval':
            terms = data['proposal']
            self.validate_manager_proposal(terms)
            if terms['guide_id'] != self.state.get('selected_guide'):
                raise ValueError('Select a guide and present exact terms first')
            approved = reply['text'].strip().lower().rstrip('.') == 'approved'
            self.state['approval'] = dict(reference=str(uuid4()), proposal=terms) if approved else None
            if not approved:
                self.state['rejections'] = [*self.state.get('rejections', []), deepcopy(terms)]
            reply.update(approval_ref=self.state['approval']['reference'] if approved else None, proposal=terms)
        elif self.actor == 'agent_a' and data['kind'] == 'substitution':
            offer = self.state.get('offer')
            if not offer or offer['proposal'] != data['proposal']:
                raise ValueError('Present the exact operator-offered substitution')
            if reply.get('matched_intent'):
                self.state['customer_reply'] = dict(reply, proposal=data['proposal'])
                reply['proposal'] = data['proposal']
            else:
                self.state['customer_reply'] = None
        response = self.trace.emit('human.response', self.actor.replace('agent', 'human'), reply,
            recipient=self.actor, operation_id=reply['interaction_id'],
            caused_by=reply.get('interrupt_event_id'))
        reply['response_event_id'] = response['event_id']
        self.state.setdefault('interactions', {})[reply['interaction_id']] = deepcopy(reply)
        if self.actor == 'agent_a':
            requirements = deepcopy(self.state.get('requirements', {}))
            references = requirements.setdefault('reply_references', {})
            references[reply['interaction_id']] = response['event_id']
            self.state['requirements'] = requirements
        if self.actor == 'agent_a' and data['kind'] == 'substitution' and reply.get('matched_intent'):
            self.state['customer_reply'] = deepcopy(reply)
        return reply

    def reply_with_customer_decision(self, decision):
        offer, reply = self.state.get('offer'), self.state.get('customer_reply')
        if not offer or not reply or reply.get('proposal') != offer['proposal']:
            raise ValueError('customer_reply_required')
        existing = self.state.get('customer_decision')
        if existing and existing.get('offer_message_id') == offer['message_id']:
            if existing['decision'] != decision:
                raise ValueError('customer_decision_already_returned')
            return {'queued': existing['message_id']}
        payload = CustomerDecisionPayload(offer_message_id=offer['message_id'], proposal=offer['proposal'],
            decision=decision, interaction_id=reply['interaction_id'],
            response_event_id=reply['response_event_id'], reply_text=reply['text'],
            planning_facts=selected_planning_facts(self.state, offer['proposal']))
        receipt = self.stage_message(f'Customer decision: {decision}. Original reply: {reply["text"]}',
                                     'request', payload=payload)
        event = self.trace.emit('customer.consent', self.actor,
            dict(proposal=offer['proposal'], accepted=decision == 'accepted',
                 offer_message_id=offer['message_id'], response_event_id=reply['response_event_id']),
            caused_by=reply['response_event_id'])
        message = self.state['outbox'][receipt['queued']]
        self.state['outbox'][receipt['queued']] = {'envelope': message, 'caused_by': event['event_id']}
        self.state['customer_decision'] = dict(payload.model_dump(mode='json'), message_id=receipt['queued'])
        return receipt

    def prepare_booking(self, terms, tool_callid=None):
        terms = Proposal.model_validate(terms).model_dump(mode='json')
        self.validate_manager_proposal(terms)
        approval = self.state.get('approval')
        if not approval or approval['proposal'] != terms:
            raise ValueError('missing_approval')
        attempt = self.state.get('booking_attempt')
        if attempt and attempt['proposal'] != terms:
            raise ValueError('idempotency_conflict')
        if attempt:
            return attempt
        idempotency_key = f'booking:{self.request_id}'
        payload = ReservationProgressPayload(status='pending', proposal=terms, idempotency_key=idempotency_key)
        message = self._envelope('Reservation operation is pending.', 'notification', payload, correlate=False)
        attempt = dict(status='prepared', proposal=terms, idempotency_key=idempotency_key,
                       progress_message_id=message['message_id'])
        self.state['booking_attempt'] = attempt
        return attempt

    def reservation_outcome(self):
        booking = self.state.get('booking')
        attempt = self.state.get('booking_attempt')
        approval = self.state.get('approval')
        decision = self.state.get('customer_decision')
        return ReservationOutcomePayload(status='confirmed' if booking else 'uncertain',
            reservation=booking, proposal=attempt['proposal'] if attempt else None,
            approval_ref=approval['reference'] if approval else None,
            decision_message_id=decision.get('source_message_id') if decision else None)

    async def reserve(self, terms):
        attempt = self.prepare_booking(terms)
        if self.state.get('booking'):
            return Reservation.model_validate(self.state['booking'])
        if attempt['progress_message_id'] not in self.state.get('dispatch_ack', {}):
            raise ValueError('booking_progress_dispatch_required')
        terms = attempt['proposal']
        days = [day for report in self.observed.get('get_weather_forecast', []) for day in report['days']
                if day['date'] == terms['date']]
        if not days or days[-1]['wind_kmh'] > 40 or days[-1]['precipitation_probability'] > 70:
            raise ValueError('A verified safe forecast is required for this date')
        routes = [route for group in self.observed.get('search_hiking_routes', []) for route in group]
        routes.extend(self.observed.get('get_route_details', []))
        if not any(route['route_id'] == terms['route_id'] for route in routes):
            raise ValueError('A verified route is required')
        available = [guide for record in self.state.get('observations', {}).values()
                     if record['tool'] == 'check_guide_availability'
                     and record['result']['status'] != 'error'
                     and record['query']['date'] == terms['date']
                     and record['query']['route_id'] == terms['route_id']
                     for guide in record['result']['data']]
        if not any(guide['guide_id'] == terms['guide_id'] and guide['available']
                   and terms['route_id'] in guide['qualifications'] for guide in available):
            raise ValueError('invalid_guide')
        request = BookingRequest(**terms, request_id=self.request_id,
            idempotency_key=attempt['idempotency_key'], approval_ref=self.state['approval']['reference'])
        permit = (attempt['idempotency_key'], self.state.get('_tool_call_id'))
        if permit not in self._booking_permits and not getattr(self.provider, 'idempotent_reservations', False):
            self.state['booking_attempt'] = dict(attempt, status='uncertain')
            raise RuntimeError('booking_outcome_uncertain')
        self._booking_permits.discard(permit)
        if attempt['status'] == 'uncertain' and not getattr(self.provider, 'idempotent_reservations', False):
            raise RuntimeError('booking_outcome_uncertain')
        try:
            result = await self.provider.reserve(request)
        except (TimeoutError, httpx.HTTPError):
            self.state['booking_attempt'] = dict(attempt, status='uncertain')
            raise
        if result.model_dump(mode='json', include=set(Proposal.model_fields)) != terms:
            raise ValueError('invalid_confirmation')
        self.state['booking'] = result.model_dump(mode='json')
        self.state['booking_attempt'] = dict(attempt, status='confirmed')
        return result

    def make_result(self, submission):
        outcome = self.state.get('received_outcome')
        if outcome and outcome['status'] == 'uncertain':
            raise RuntimeError('booking_outcome_uncertain')
        receipt = outcome.get('reservation') if outcome else None
        if submission.status == 'confirmed':
            if not receipt:
                raise ValueError('No verified reservation is available')
            if any(getattr(submission, key).isoformat() != receipt[key] if key == 'date'
                   else getattr(submission, key) != receipt[key] for key in ('route_id', 'date', 'guide_id')):
                raise ValueError('Result disagrees with booking')
            if sorted(submission.equipment_items) != sorted(receipt['equipment']):
                raise ValueError('Result disagrees with booking')
        elif receipt:
            raise ValueError('Result disagrees with booking')
        elif self.state.get('booking_progress') and not outcome:
            raise RuntimeError('booking_outcome_uncertain')
        return TripResult(**submission.model_dump(), request_id=self.request_id,
                          reservation_id=receipt['reservation_id'] if receipt else None)

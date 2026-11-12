"""Checkpoint-backed receive and dispatch for one private agent thread."""

import asyncio
from copy import deepcopy

from app.models.messages import PeerEnvelope


class AgentDriver:
    def __init__(self, graph, actor, config, bus):
        self.graph = graph
        self.actor = actor
        self.config = config
        self.bus = bus
        self.lock = asyncio.Lock()

    async def get_state(self):
        snapshot = await self.graph.aget_state(self.config)
        return deepcopy(snapshot.values)

    async def update(self, values):
        await self.graph.aupdate_state(self.config, deepcopy(values))

    async def receive(self, envelope):
        message = PeerEnvelope.model_validate(envelope)
        data = message.model_dump(mode='json')
        if message.recipient != self.actor or message.request_id != self.bus.request_id:
            raise ValueError('invalid_message_route')
        async with self.lock:
            state = await self.get_state()
            if state.get('request_id', message.request_id) != message.request_id:
                raise ValueError('invalid_request_id')
            previous = state.get('inbox', {}).get(message.message_id)
            if previous is not None:
                if previous != data:
                    raise ValueError('message_id_conflict')
                self._acknowledge(message.message_id)
                return False
            updates = {'inbox': {message.message_id: data}, 'incoming': data, 'trip_status': 'working'}
            updates.update(self._payload_updates(state, message))
            await self.update(updates)
            self._acknowledge(message.message_id)
            return True

    def _acknowledge(self, message_id):
        # Direct checkpoint restore need not have a live transport receipt yet.
        if message_id in self.bus.envelopes:
            self.bus.acknowledge_received(message_id)

    @staticmethod
    def _payload_updates(state, message):
        payload = message.payload
        if payload is None:
            return {}
        data = payload.model_dump(mode='json')
        kind = payload.kind
        if kind == 'trip_request':
            updates = {'planning_facts': {fact.id: fact.model_dump(mode='json')
                                         for fact in payload.planning_facts}}
            if state.get('original_proposal') is None:
                updates['original_proposal'] = payload.terms.model_dump(mode='json')
            return updates
        if kind == 'trip_offer':
            return {'offer': {'proposal': data['proposal'],
                             'message_id': message.message_id,
                             'accepted': None, 'returned': False},
                    'customer_reply': None, 'customer_decision': None}
        if kind == 'customer_decision':
            offer = state.get('offer')
            if (not offer or offer['message_id'] != payload.offer_message_id
                    or offer['proposal'] != data['proposal']):
                raise ValueError('customer_decision_offer_mismatch')
            return {'planning_facts': {fact.id: fact.model_dump(mode='json') for fact in payload.planning_facts},
                    'offer': {**offer, 'accepted': payload.decision == 'accepted',
                              'returned': True, 'decision_message_id': message.message_id},
                    'customer_decision': {**data, 'source_message_id': message.message_id}}
        if kind == 'reservation_progress':
            return {'booking_progress': {**data, 'source_message_id': message.message_id}}
        if kind == 'reservation_outcome':
            return {'received_outcome': {**data, 'source_message_id': message.message_id}}
        return {}

    async def flush_outbox(self):
        async with self.lock:
            state = await self.get_state()
            for identity, record in state.get('outbox', {}).items():
                if state.get('dispatch_ack', {}).get(identity) == 'sent':
                    continue
                envelope = PeerEnvelope.model_validate(record.get('envelope', record))
                if envelope.message_id != identity or envelope.sender != self.actor:
                    raise ValueError('invalid_outbox_identity')
                if envelope.request_id != state.get('request_id'):
                    raise ValueError('invalid_request_id')
                self.bus.send_envelope(envelope, caused_by=record.get('caused_by'))
                await self.update({'dispatch_ack': {identity: 'sent'}})

    async def claim_booking_execution(self, context):
        if self.actor != 'agent_b':
            return False
        async with self.lock:
            snapshot = await self.graph.aget_state(self.config)
            if 'tools' not in snapshot.next:
                return False
            state = snapshot.values
            attempt = state.get('booking_attempt')
            if not attempt or attempt['status'] != 'prepared':
                return False
            calls = getattr(state['messages'][-1], 'tool_calls', [])
            call = next((item for item in calls if item['name'] == 'create_tour_reservation'), None)
            if call is None or attempt['progress_message_id'] not in state.get('dispatch_ack', {}):
                return False
            await self.update({'booking_attempt': {**attempt, 'status': 'executing', 'tool_call_id': call['id']}})
            context.grant_booking_execution(attempt['idempotency_key'], call['id'])
            return True

import asyncio

import pytest

from app.messaging.bus import MessageBus
from app.observability.trace import TraceRecorder


def test_stable_envelope_dispatch_deduplicates_and_acknowledges_after_checkpoint():
    from uuid import uuid4
    from app.models.messages import PeerEnvelope

    async def run():
        bus = MessageBus('r', TraceRecorder({}), 30, 20)
        request = PeerEnvelope(message_id=str(uuid4()), request_id='r', sender='agent_a',
            recipient='agent_b', type='request', content='Plan', timestamp='2026-11-12T12:00:00Z',
            payload=dict(kind='trip_request', terms=dict(route_id='route', date='2026-11-10', equipment={})))
        assert bus.send_envelope(request) == request.message_id
        assert bus.send_envelope(request) == request.message_id
        assert bus.count == 1
        incoming = await bus.receive('agent_b')
        assert request.message_id not in bus.seen
        bus.acknowledge_received(incoming['message_id'])
        assert request.message_id in bus.seen
        reply = PeerEnvelope(message_id=str(uuid4()), request_id='r', sender='agent_b',
            recipient='agent_a', correlation_id=request.message_id, type='response', content='Unavailable',
            timestamp='2026-11-12T12:00:01Z', payload=dict(kind='availability_result', reason='No guide'))
        bus.send_envelope(reply)
        received = await bus.receive('agent_a')
        assert bus.pending
        bus.acknowledge_received(received['message_id'])
        assert not bus.pending

    asyncio.run(run())


def test_envelope_transport_rejects_conflicts_and_cross_session_messages():
    from app.models.messages import PeerEnvelope
    bus = MessageBus('r', TraceRecorder({}), 30, 20)
    data = dict(message_id='one', request_id='r', sender='agent_a', recipient='agent_b',
                type='notification', content='Hello', timestamp='2026-11-12T12:00:00Z')
    bus.send_envelope(PeerEnvelope(**data))
    with pytest.raises(ValueError, match='message_id_conflict'):
        bus.send_envelope(PeerEnvelope(**{**data, 'content': 'Changed'}))
    with pytest.raises(ValueError, match='invalid_request_id'):
        bus.send_envelope(PeerEnvelope(**{**data, 'request_id': 'another'}))


def test_request_reply():
    async def run():
        bus = MessageBus("r", TraceRecorder({}), 30, 20)
        request = bus.send("agent_a", "proposal", "request")
        assert await bus.receive("agent_b") == request
        reply = bus.send("agent_b", "confirmed", "response", request)
        assert (await bus.receive("agent_a"))["correlation_id"] == request["message_id"]
        with pytest.raises(ValueError):
            bus.send("agent_b", "duplicate", "response", request)
        assert not bus.pending

    asyncio.run(run())


def test_peer_send_in_request_turn_closes_request():
    from private_agent_helpers import make_context, scoped
    from app.models.messages import PeerEnvelope
    async def execute():
        bus = MessageBus('r', TraceRecorder({}), 30, 20)
        context = make_context('agent_b')
        context.request_id = 'r'
        request = bus.send('agent_a', 'proposal', 'request')
        state = {'incoming': await bus.receive('agent_b')}
        with scoped(context, state):
            identity = context.stage_message('operator update', 'notification')['queued']
        bus.send_envelope(PeerEnvelope.model_validate(state['outbox'][identity]))
        reply = await bus.receive('agent_a')
        assert reply['correlation_id'] == request['message_id']
        bus.acknowledge_received(reply['message_id'])
        assert not bus.pending
    asyncio.run(execute())

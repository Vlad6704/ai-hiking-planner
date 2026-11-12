import pytest


def test_booking_requires_locally_received_request():
    from private_agent_helpers import make_context, scoped
    context = make_context('agent_b')
    with scoped(context, {}), pytest.raises(ValueError, match='original_proposal_required'):
        context.validate_manager_proposal(dict(route_id='route', date='2026-11-10', guide_id='guide', equipment={}))


def test_received_confirmation_is_required_for_planner_result():
    from private_agent_helpers import make_context, scoped
    from app.models.contracts import TripSubmission
    from uuid import uuid4
    context = make_context()
    with scoped(context, {}), pytest.raises(ValueError, match='verified reservation'):
        context.make_result(TripSubmission(
            status='confirmed', route_id='route', date='2026-11-10', guide_id='guide'))


def test_received_uncertain_outcome_cannot_be_reported_as_failed_trip():
    from private_agent_helpers import make_context, scoped
    from app.models.contracts import TripSubmission
    context = make_context()
    with scoped(context, {'received_outcome': {'status': 'uncertain'}}):
        with pytest.raises(RuntimeError, match='booking_outcome_uncertain'):
            context.make_result(TripSubmission(status='failed', failure_reason='No booking'))


def test_booking_outcome_references_the_received_customer_decision():
    from app.agents.driver import AgentDriver
    from app.models.messages import PeerEnvelope
    from private_agent_helpers import make_context, scoped

    context = make_context('agent_b')
    proposal = dict(route_id='route', date='2026-11-10', guide_id='guide', equipment={})
    state = dict(offer=dict(message_id='offer-one', proposal=proposal),
        booking=dict(**proposal, reservation_id='TR-ABCDEFGH', status='confirmed',
                     created_at='2026-11-12T12:00:00Z'),
        booking_attempt=dict(proposal=proposal), approval=dict(reference='approved'))
    decision = PeerEnvelope(message_id='customer-decision-one', request_id=context.request_id,
        sender='agent_a', recipient='agent_b', type='request', timestamp='2026-11-12T12:00:00Z',
        payload=dict(kind='customer_decision', offer_message_id='offer-one', proposal=proposal,
                     decision='accepted', interaction_id='interaction-one',
                     response_event_id='reply-event-one', reply_text='Yes'))
    state.update(AgentDriver._payload_updates(state, decision))
    with scoped(context, state):
        assert context.reservation_outcome().decision_message_id == decision.message_id

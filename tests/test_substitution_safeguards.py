"""Consent validation across separate agent-owned records."""
import asyncio
from copy import deepcopy

import pytest

from app.agents.driver import AgentDriver
from app.agents.tools import bind_tools
from app.models.messages import PeerEnvelope
from app.models.contracts import Proposal, TripProposal
from private_agent_helpers import make_context, scoped

TERMS = dict(route_id='PR-PNPE-2:long', date='2026-11-10', guide_id='luis', equipment={'poncho': 1})
ORIGINAL = dict(route_id='PR-PNPE-2:long', date='2026-11-10', equipment={'rain jacket': 1})


def inventory(context, state, items, quantities, date='2026-11-10'):
    with scoped(context, state):
        context.record_observation('check_equipment_inventory', dict(date=date, items=items), dict(
            status='success', data=dict(quantities=quantities, unavailable=[item for item, q in items.items() if quantities.get(item, 0) < q]),
            source='mock', mode='mock'))


def setup_offer():
    a, b = make_context(), make_context('agent_b')
    b.request_id = a.request_id
    a_state, b_state = {}, dict(original_proposal=deepcopy(ORIGINAL), selected_guide='luis')
    inventory(b, b_state, {'rain jacket': 1}, {'rain jacket': 0})
    inventory(b, b_state, {'poncho': 1}, {'poncho': 3})
    with scoped(b, b_state):
        identity = b.stage_message('Please offer the poncho', 'request', Proposal(**TERMS))['queued']
    message = PeerEnvelope.model_validate(b_state['outbox'][identity])
    a_state.update(AgentDriver._payload_updates(a_state, message))
    a_state['incoming'] = message.model_dump(mode='json')
    return a, b, a_state, b_state


def reply(a, state, text='Sounds good to me', matched=True):
    with scoped(a, state):
        return a.process_human_reply(dict(kind='substitution', proposal=TERMS), dict(
            text=text, interaction_id='customer-one', matched_intent=['manual'] if matched else [], match_score=1))


def deliver_decision(a_state, b_state):
    message_id = a_state['customer_decision']['message_id']
    envelope = a_state['outbox'][message_id]['envelope']
    b_state.update(AgentDriver._payload_updates(b_state, PeerEnvelope.model_validate(envelope)))


@pytest.mark.parametrize('manual', [True, False])
def test_reply_preserves_words_without_interpreting_them(manual):
    a, _, state, _ = setup_offer()
    result = reply(a, state)
    assert result['text'] == 'Sounds good to me'
    assert 'accepted' not in result
    assert state['customer_reply']['response_event_id'] == a.trace.events[-1]['event_id']
    assert not state.get('customer_decision')


@pytest.mark.parametrize('decision', ['accepted', 'declined'])
def test_decision_tool_records_and_sends_once(decision):
    a, b, state, other = setup_offer()
    reply(a, state)
    with scoped(a, state):
        first = a.reply_with_customer_decision(decision)
        assert a.reply_with_customer_decision(decision) == first
        with pytest.raises(ValueError, match='already_returned'):
            a.reply_with_customer_decision('declined' if decision == 'accepted' else 'accepted')
    assert len(state['outbox']) == 1
    assert not other.get('customer_decision')
    deliver_decision(state, other)
    with scoped(b, other):
        if decision == 'accepted':
            b.validate_manager_proposal(TERMS)
        else:
            with pytest.raises(ValueError, match='customer_consent_required'):
                b.validate_manager_proposal(TERMS)
    assert 'reply_with_customer_decision' not in {tool.name for tool in bind_tools('agent_b', b)}


def test_missing_and_superseded_reply_cannot_authorize_decision():
    a, _, state, _ = setup_offer()
    with scoped(a, state):
        with pytest.raises(ValueError, match='customer_reply_required'):
            a.reply_with_customer_decision('accepted')
    reply(a, state)
    state['offer'] = dict(proposal={**TERMS, 'date': '2026-11-11'}, message_id='new-offer')
    with scoped(a, state):
        with pytest.raises(ValueError, match='customer_reply_required'):
            a.reply_with_customer_decision('accepted')


def test_failed_send_can_be_retried_without_granting_consent():
    a, b, state, other = setup_offer()
    reply(a, state)
    with scoped(a, state):
        receipt = a.reply_with_customer_decision('accepted')
    # Staging is durable intent, not evidence that the peer received it.
    with scoped(b, other):
        with pytest.raises(ValueError, match='customer_consent_required'):
            b.validate_manager_proposal(TERMS)
    with scoped(a, state):
        assert a.reply_with_customer_decision('accepted') == receipt
    deliver_decision(state, other)
    with scoped(b, other):
        b.validate_manager_proposal(TERMS)


@pytest.mark.parametrize('answer', ['Maybe', 'Yes, but on the 12th.'])
def test_unresolved_reply_and_plain_peer_message_do_not_grant_consent(answer):
    a, b, state, other = setup_offer()
    reply(a, state, answer)
    with scoped(a, state):
        a.stage_message('Please verify different terms', 'request', TripProposal(**ORIGINAL))
    with scoped(b, other):
        with pytest.raises(ValueError, match='customer_consent_required'):
            b.validate_manager_proposal(TERMS)


def test_unmatched_substitution_question_does_not_record_refusal():
    a, _, state, _ = setup_offer()
    result = reply(a, state, 'Could you clarify?', matched=False)
    assert not result['matched_intent']
    assert not state.get('customer_reply') and not state.get('customer_decision')


@pytest.mark.parametrize('check_date', [None, '2026-11-11'])
def test_manager_cannot_approve_inventory_that_was_not_checked(check_date):
    b = make_context('agent_b')
    state = dict(original_proposal=deepcopy(ORIGINAL))
    if check_date:
        inventory(b, state, {'poncho': 1}, {'poncho': 3}, check_date)
    with scoped(b, state):
        with pytest.raises(ValueError, match='verified_equipment_required'):
            b.validate_manager_proposal(TERMS)


def test_any_explicit_substitution_offer_requires_customer_consent():
    _, b, _, state = setup_offer()
    with scoped(b, state):
        with pytest.raises(ValueError, match='customer_consent_required'):
            b.validate_manager_proposal(TERMS)


def test_unavailable_requested_gear_cannot_reach_manager():
    _, b, _, state = setup_offer()
    with scoped(b, state):
        with pytest.raises(ValueError, match='verified_equipment_required'):
            b.validate_manager_proposal({**TERMS, 'equipment': {'rain jacket': 1}})


def test_substitute_requires_customer_consent_delivered_to_operator():
    test_failed_send_can_be_retried_without_granting_consent()


def test_declined_or_ambiguous_substitution_cannot_reach_manager():
    a, b, state, other = setup_offer()
    reply(a, state, 'No, I decline')
    with scoped(a, state):
        a.reply_with_customer_decision('declined')
    deliver_decision(state, other)
    with scoped(b, other):
        with pytest.raises(ValueError, match='customer_consent_required'):
            b.validate_manager_proposal(TERMS)


def test_rejected_manager_terms_require_customer_agreement_to_replacement():
    b = make_context('agent_b')
    state = dict(original_proposal=deepcopy(ORIGINAL), rejections=[{**TERMS, 'equipment': {'rain jacket': 1}}])
    inventory(b, state, {'poncho': 1}, {'poncho': 3})
    with scoped(b, state):
        with pytest.raises(ValueError, match='customer_consent_required'):
            b.validate_manager_proposal(TERMS)


def test_booking_request_requires_original_proposal_but_notifications_are_allowed():
    a = make_context()
    with scoped(a, {}):
        assert 'queued' in a.stage_message('Informational update')
        with pytest.raises(ValueError, match='original_proposal_required'):
            a.stage_message('Book my request', 'request')

import pytest

from app.humans.simulator import HumanSimulator


def test_match_intents():
    human = HumanSimulator(
        {"experience": (["experience"], "Beginner"), "gear": (["boots"], "Yes")}
    )
    assert human.answer("experience and boots")["text"] == "Beginner Yes"
    for _ in range(2):
        assert human.answer("huh")["matched_intent"] == []
    with pytest.raises(ValueError, match="human_response_unmatched"):
        human.answer("huh")


def test_manager_selection_and_approval():
    from private_agent_helpers import make_context, scoped
    context = make_context('agent_b')
    terms = dict(route_id='trail', date='2026-11-10', guide_id='b', equipment={})
    state = dict(original_proposal={k:v for k,v in terms.items() if k != 'guide_id'},
                 observations={'guides': dict(tool='check_guide_availability', query={},
                     result=dict(status='success', data=[{'guide_id':'a'},{'guide_id':'b'}]))})
    with scoped(context, state):
        assert context.process_human_reply(dict(kind='selection', options=['a','b']),
            dict(text='2', interaction_id='selection'))['guide_id'] == 'b'
        answer = context.process_human_reply(dict(kind='approval', proposal=terms),
            dict(text='Approved', interaction_id='approval'))
        assert answer['approval_ref'] == context.state['approval']['reference']
        with pytest.raises(ValueError, match='missing_approval'):
            context.prepare_booking({**terms, 'guide_id':'a'})


def test_structured_substitution_avoids_competing_keyword_rules():
    human = HumanSimulator({
        "gear": (["rain jacket"], "Please rent a rain jacket."),
        "date": (["November"], "November 10."),
        "substitution": (["poncho", "substitution"], "Yes, I accept the poncho substitution."),
    })
    result = human.answer("On November 10 replace the rain jacket with a poncho?", intent="substitution")
    assert result["matched_intent"] == ["substitution"]
    assert result["text"] == "Yes, I accept the poncho substitution."


def test_guide_shortage_fixture_accepts_its_alternative_date():
    from app.simulation.scenario import load_scenario
    human = HumanSimulator(load_scenario("guide_unavailable")["rules"])
    reply = human.answer("Do you accept November 11 instead?", intent="substitution")
    assert reply["matched_intent"] == ["substitution"]
    assert reply["text"].startswith("Yes, I accept")

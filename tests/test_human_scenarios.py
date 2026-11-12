import pytest

from app.humans.simulator import HumanSimulator
from app.simulation.scenario import load_scenario, scenarios


QUESTIONS = [
    ("November 10 looks suitable (15°C, 10% chance of rain, 8 km/h wind). Would you prefer the easy Lakes of Covadonga long loop (5 km, about 2.5 hours) or short loop (3 km, about 1 hour)? What is your hiking experience, how many people are going, and what hiking gear do you already own or need to rent (especially hiking boots and rain protection)?",
     {"route", "experience", "group", "gear"}),
    ("Do you agree to the Lakes of Covadonga long loop (5 km, approximately 2.5 hours) on November 10? Please also tell me your hiking experience and whether the rain jacket rental is for one hiker or more.",
     {"route", "experience", "group"}),
    ("As a beginner, would you like to book the Lakes of Covadonga short loop (3 km, 1 hour) or long loop (5 km, 2.5 hours) for November 10? Is it one rain jacket you need to rent? Please answer both.",
     {"route", "gear", "group"}),
    ("Which route do you want: the 1-hour short Lakes of Covadonga loop or the 2.5-hour long loop?",
     {"route"}),
    ("No qualified guide is available November 10 for the 2.5-hour Lakes of Covadonga route. What alternative date would you like? I'll check its weather before requesting a guide; your one rain jacket rental remains part of the request.",
     {"alternative_date"}),
    ("Which exact alternative calendar date (for example, November 11 or November 12, 2026) would you like, since November 10 has no available guide?",
     {"alternative_date"}),
    ("To continue I need you to choose a different day. Can you hike on November 11, 2026?",
     {"alternative_date"}),
]


@pytest.mark.parametrize("name", scenarios())
@pytest.mark.parametrize("question, expected", QUESTIONS)
def test_scenario_answers_observed_questions(name, question, expected):
    case = load_scenario(name)
    human = HumanSimulator(case["rules"])
    reply = human.answer(question)
    assert expected <= set(reply["matched_intent"]), reply
    if "route" in expected:
        assert "long loop" in reply["text"]
    if "alternative_date" in expected:
        if case.get('allow_alternative_date') is False:
            assert case['expected_date'] in reply['text']
            assert 'No, I cannot change the date.' in reply['text']
        else:
            assert "November 11" in reply["text"]
    assert "Could you clarify" not in reply["text"]
    assert "substitution" not in reply["matched_intent"]


def test_identical_keyword_evidence_remains_ambiguous():
    human = HumanSimulator({"a": (["confirm"], "A"), "b": (["confirm"], "B")})
    assert human.answer("Confirm?")["matched_intent"] == []


def test_multi_intent_answers_are_not_repeated():
    human = HumanSimulator({"experience": (["experience"], "Beginner"),
                            "gear": (["equipment"], "Own boots")})
    reply = human.answer("What experience and equipment? Experience? Equipment?")
    assert reply["matched_intent"] == ["experience", "gear"]
    assert reply["text"] == "Beginner Own boots"


def test_observed_exact_substitution_question_uses_customer_decision():
    human = HumanSimulator(load_scenario("guide_unavailable")["rules"])
    reply = human.answer(
        "The operator offers this exact substitute for the unavailable November 10 hike: "
        "Lakes of Covadonga long loop (route PR-PNPE-2:long) on November 11, 2026, "
        "with the operator-selected guide and one rented rain jacket. "
        "Do you explicitly accept this exact substitution? Please answer yes or no.",
        intent="substitution",
    )
    assert reply["matched_intent"] == ["substitution"]
    assert reply["text"].startswith("Yes, I accept")


def test_real_alternative_date_uses_forecast_window(monkeypatch):
    from datetime import date
    monkeypatch.setattr("app.simulation.scenario.planning_date", lambda: date(2031, 12, 31))
    human = HumanSimulator(load_scenario("guide_unavailable", "real")["rules"])
    reply = human.answer("What alternative date would you like?")
    assert "2032-01-02" in reply["text"]
    assert "November" not in reply["text"]
    consent = human.answer("Do you accept this alternative?", intent="substitution")
    assert "2032-01-02" in consent["text"]
    assert load_scenario("guide_unavailable", "real")["no_guides"] == "2032-01-01"


def test_authored_consent_rejects_a_different_proposal():
    case = load_scenario("guide_unavailable")
    human = HumanSimulator(case["rules"], consent_terms=case["substitution_terms"])
    correct = dict(route_id="PR-PNPE-2:long", date="2026-11-11", equipment={"rain jacket": 1})
    assert human.answer("Do you accept?", intent="substitution", proposal=correct)["text"].startswith("Yes")
    for field, value in [("route_id", "PR-PNPE-2:short"), ("date", "2026-11-12"),
                         ("equipment", {})]:
        reply = human.answer("Do you accept?", intent="substitution",
                             proposal={**correct, field: value})
        assert reply["text"].startswith("No")


def test_equipment_consent_uses_selected_route_before_preference_is_disclosed():
    case = load_scenario("hitl_rejection")
    human = HumanSimulator(case["rules"], consent_terms=case["substitution_terms"])
    human.answer("What is your hiking experience and preferred duration? "
                 "What rain protection do you need to rent?")
    original = dict(route_id="PR-PNPE-2:short", date="2026-11-10", equipment={"rain jacket": 1})
    offered = {**original, "equipment": {"poncho": 1}}
    reply = human.answer("Do you accept this poncho substitution?", intent="substitution",
                         proposal=offered, original_proposal=original)
    assert reply["text"].startswith("Yes")
    changed_route = {**offered, "route_id": "PR-PNPE-2:long"}
    assert human.answer("Do you accept?", intent="substitution", proposal=changed_route,
                        original_proposal=original)["text"].startswith("No")


def test_disclosed_route_preference_remains_a_consent_constraint():
    case = load_scenario("hitl_rejection")
    human = HumanSimulator(case["rules"], consent_terms=case["substitution_terms"])
    assert "long loop" in human.answer("Which route do you prefer?")["text"]
    original = dict(route_id="PR-PNPE-2:short", date="2026-11-10", equipment={"rain jacket": 1})
    offered = {**original, "equipment": {"poncho": 1}}
    reply = human.answer("Do you accept?", intent="substitution", proposal=offered,
                         original_proposal=original)
    assert reply["text"].startswith("No")

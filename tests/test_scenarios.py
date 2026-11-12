from app.simulation.scenario import load_scenario, scenarios


def test_baseline_and_equipment_shortage_scenario_contracts():
    assert {"happy_path", "bad_weather", "guide_unavailable", "hitl_rejection",
            "external_service_failure", "equipment_shortage"} <= set(scenarios())
    for name in scenarios():
        case = load_scenario(name)
        assert case["id"] == name and case["expected_date"] in case["guides"]


def test_happy_path_discloses_expected_route_before_follow_up_questions():
    for mode in ('mock', 'real'):
        case = load_scenario('happy_path', mode)
        assert case['expected_route_id'] == 'PR-PNPE-2:long'
        assert case['expected_route_id'] in case['initial']


def test_happy_path_rejects_alternative_dates_without_changing_other_scenarios():
    from datetime import date, timedelta
    from app.humans.simulator import HumanSimulator
    for mode in ('mock', 'real'):
        case = load_scenario('happy_path', mode)
        expected = case['expected_date']
        assert case['acceptable_dates'] == [expected]
        human = HumanSimulator(case['rules'], consent_terms=case['substitution_terms'])
        assert expected in human.answer('What date works?')['text']
        assert human.answer('Can you choose another date?')['text'].startswith('No')
        tomorrow = str(date.fromisoformat(expected) + timedelta(days=1))
        proposal = dict(route_id=case['preferred_route_id'], date=tomorrow, equipment={'rain jacket': 1})
        assert human.answer('Accept the offer?', intent='substitution', proposal=proposal)['text'].startswith('No')
    guide = load_scenario('guide_unavailable')
    assert 'November 11 works' in HumanSimulator(guide['rules']).answer('Would another date work?')['text']

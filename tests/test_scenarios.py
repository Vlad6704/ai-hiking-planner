from app.simulation.scenario import load_scenario, scenarios


def test_five_scenario_contracts():
    assert len(scenarios()) == 5
    for name in scenarios():
        case = load_scenario(name)
        assert case["id"] == name and case["expected_date"] in case["guides"]

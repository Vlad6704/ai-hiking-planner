from app.simulation.scenario import load_scenario, scenarios


def test_baseline_and_equipment_shortage_scenario_contracts():
    assert {"happy_path", "bad_weather", "guide_unavailable", "hitl_rejection",
            "external_service_failure", "equipment_shortage"} <= set(scenarios())
    for name in scenarios():
        case = load_scenario(name)
        assert case["id"] == name and case["expected_date"] in case["guides"]

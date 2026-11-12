import json
from datetime import timedelta

import yaml

from app.tools.planning import ROOT
from app.time_context import planning_date


def scenarios():
    return sorted(p.stem for p in (ROOT / "scenarios").glob("*.yaml"))


def load_scenario(name, mode="mock"):
    if name not in scenarios():
        raise ValueError("Unknown scenario")
    spec = yaml.safe_load(
        (ROOT / "scenarios" / f"{name}.yaml").read_text(encoding="utf-8")
    )
    case = json.loads(
        (ROOT / "snapshots" / spec["snapshot"]).read_text(encoding="utf-8")
    )
    case["rules"].update(spec.get("rules", {}))
    case.update({key: value for key, value in spec.items() if key != "rules"})
    if "storm" in case:
        case["weather"]["days"][0]["wind_kmh"] = 75
    if "no_guides" in case:
        case["guides"][case["no_guides"]] = []
    if mode == "real":
        first = planning_date() + timedelta(days=1)
        if "no_guides" in case:
            case["no_guides"] = str(first)
        case["initial"] = (
            f"Arrange an easy hike in Picos de Europa on {first}, maximum four hours."
        )
        if case.get('expected_route_id'):
            case['initial'] += f" Use route {case['expected_route_id']}."
        case["rules"]["date"][1] = (
            f"I prefer {first}, or {first + timedelta(days=1)} if needed."
        )
        case["rules"]["alternative_date"] = [
            ["alternative date", "another date", "different date", "different day",
             str(first + timedelta(days=1))],
            f"Yes, {first + timedelta(days=1)} works for the alternative hike.",
        ]
        if name == "guide_unavailable":
            case["rules"]["substitution"] = [
                ["accept", "alternative", "substitute", "replacement"],
                f"Yes, I accept the alternative guided hike on {first + timedelta(days=1)} "
                "with the proposed guide and rental rain jacket.",
            ]
        case["expected_date"] = str(first)
        case["acceptable_dates"] = [str(first), str(first + timedelta(days=1))]
    if case.get('allow_alternative_date') is False:
        only_date = case['expected_date']
        case['acceptable_dates'] = [only_date]
        case['initial'] += f" Only {only_date} works; I cannot change the date."
        case['rules']['date'][1] = f"I can only hike on {only_date}; other dates do not work."
        case['rules']['alternative_date'][1] = f"No, I cannot change the date. Only {only_date} works."
    if "substitution_equipment" in case:
        case["substitution_terms"] = dict(
            route_id=case["preferred_route_id"],
            dates=case.get("acceptable_dates", [case["expected_date"]]),
            equipment=case["substitution_equipment"],
        )
    return case

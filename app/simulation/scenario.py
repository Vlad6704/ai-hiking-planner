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
    case.update(spec)
    if "storm" in case:
        case["weather"]["days"][0]["wind_kmh"] = 75
    if "no_guides" in case:
        case["guides"][case["no_guides"]] = []
    if mode == "real":
        first = planning_date() + timedelta(days=1)
        case["initial"] = (
            f"Arrange an easy hike in Picos de Europa on {first}, maximum four hours."
        )
        case["rules"]["date"][1] = (
            f"I prefer {first}, or {first + timedelta(days=1)} if needed."
        )
        case["expected_date"] = str(first)
        case["acceptable_dates"] = [str(first), str(first + timedelta(days=1))]
    return case

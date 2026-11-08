import pytest

from app.humans.approval import ApprovalRegistry
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
    registry = ApprovalRegistry()
    assert registry.select("2", ["a", "b"]) == "b"
    ref = registry.record("r", {"guide_id": "b"}, "approved")
    registry.require("r", ref, {"guide_id": "b"})
    with pytest.raises(ValueError):
        registry.require("r", ref, {"guide_id": "a"})

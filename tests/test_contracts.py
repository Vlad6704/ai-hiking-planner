from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.contracts import Guide, Proposal, ToolResult, TripResult
from app.simulation.config import Settings


@pytest.mark.parametrize("field", ["route_id", "date", "guide_id", "reservation_id"])
def test_trip_result_conditions(field):
    fields = dict(
        request_id=uuid4(),
        status="confirmed",
        route_id="trail",
        date="2026-11-12",
        guide_id="guide",
        reservation_id="reservation",
        equipment_items=[],
        failure_reason=None,
    )
    assert TripResult(**fields).status == "confirmed"
    fields[field] = None
    with pytest.raises(ValidationError):
        TripResult(**fields)


def test_tool_contracts():
    assert (
        ToolResult[list[Guide]](
            status="success", data=[], source="fixture", mode="mock"
        ).data
        == []
    )
    with pytest.raises(ValidationError):
        Proposal(route_id="trail", date="invalid", guide_id="guide", equipment={})
    with pytest.raises(ValidationError):
        Proposal(
            route_id="trail",
            date="2026-11-12",
            guide_id="guide",
            equipment={"poles": 0},
        )
    with pytest.raises(ValidationError):
        TripResult(request_id=uuid4(), status="failed", failure_reason="  ")
    settings = Settings()
    assert (
        settings.attempts,
        settings.steps,
        settings.exchanges,
        settings.timeout,
    ) == (3, 100, 20, 120)

from app.evaluation.checks import metrics


def test_metric_denominators():
    report = metrics(
        [
            {"type": kind, "data": {}}
            for kind in ["tool.called", "tool.failed", "tool.called", "tool.completed"]
        ]
    )
    assert report["tool_failure_rate"] == 0.5
    assert report["recovery_success_rate"] is None


def test_reapproval_after_booking_does_not_invalidate_previous_creation():
    from app.evaluation.checks import approved_bookings

    terms = {"route_id": "r", "date": "2026-11-10", "guide_id": "g", "equipment": {}}

    def approve(seq):
        return {
            "type": "human.response",
            "actor": "human_b",
            "seq": seq,
            "data": {
                "approval_ref": str(seq),
                "proposal": terms,
                "matched_intent": ["approval"],
            },
        }

    def event(seq, kind, op):
        return {
            "type": kind,
            "seq": seq,
            "operation_id": op,
            "data": {
                "tool": "create_tour_reservation",
                "output": {"data": {**terms, "reservation_id": "same"}},
            },
        }

    first = [approve(1), event(2, "tool.called", "a"), event(3, "tool.completed", "a")]
    assert approved_bookings(
        first
        + [approve(4), event(5, "tool.called", "b"), event(6, "tool.completed", "b")]
    )
    assert not approved_bookings(first[1:] + [approve(4)])

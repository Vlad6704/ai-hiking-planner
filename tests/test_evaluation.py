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

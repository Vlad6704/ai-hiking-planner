"""Record manual session outcomes without evaluating scenario expectations."""


def trip_message(result):
    if result.status == "failed":
        return "We couldn't complete your request. Please try again later."
    equipment = ", ".join(sorted(result.equipment_items)) or "none"
    return (
        f"Confirmed {result.route_id} on {result.date} with {result.guide_id}. "
        f"Reservation {result.reservation_id}. Equipment: {equipment}."
    )


def manual_outcome(run, *, status=None):
    if status is None:
        status = 'error' if run.error else getattr(run.result, 'status', 'incomplete')
    return dict(
        status=status,
        trip_result=run.result.model_dump(mode='json') if run.result else None,
        error=run.error,
    )

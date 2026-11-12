from app.tools.reservation_codes import reservation_codes
from datetime import UTC, datetime

from app.models.contracts import (
    BookingRequest,
    Guide,
    GuideQuery,
    Inventory,
    InventoryQuery,
    Proposal,
    Reservation,
)


class MockOperator:
    idempotent_reservations = True

    def __init__(self, schedule, stock, routes, default_guides=()):
        self.schedule = schedule
        self.stock = stock
        self.routes = routes
        self.default_guides = default_guides
        self.created = {}

    async def guides(self, query):
        return [
            Guide(
                guide_id=gid,
                name=gid.title(),
                available=True,
                qualifications=[query.route_id],
            )
            for gid in self.schedule.get(str(query.date), self.default_guides)
            if query.route_id in self.routes
        ]

    async def inventory(self, query):
        quantities = {item: self.stock.get(item, 0) for item in query.items}
        return Inventory(
            quantities=quantities,
            unavailable=[k for k, v in query.items.items() if quantities[k] < v],
        )

    async def reserve(self, request):
        if request.idempotency_key not in self.created:
            self.created[request.idempotency_key] = confirmation(request)
        return self.created[request.idempotency_key]


def confirmation(request):
    terms = request.model_dump(include=set(Proposal.model_fields))
    return Reservation(
        **terms,
        reservation_id=reservation_codes.issue(request.request_id),
        status="confirmed",
        created_at=datetime.now(UTC),
    )

import asyncio
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
    def __init__(self, schedule, stock, routes):
        self.schedule = schedule
        self.stock = stock
        self.routes = routes
        self.created = {}

    async def guides(self, query):
        return [
            Guide(
                guide_id=gid,
                name=gid.title(),
                available=True,
                qualifications=self.routes,
            )
            for gid in self.schedule.get(str(query.date), [])
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
        reservation_id=f"tour-{request.request_id}",
        status="confirmed",
        created_at=datetime.now(UTC),
    )


class OperatorTools:
    def __init__(self, request_id, approvals, provider):
        self.request_id = request_id
        self.approvals = approvals
        self.provider = provider
        self.lock = asyncio.Lock()
        self.terms = None
        self.result = None

    async def reserve(self, request: BookingRequest):
        async with self.lock:
            if (
                str(request.request_id) != self.request_id
                or request.idempotency_key != f"booking:{self.request_id}"
            ):
                raise ValueError("invalid_identity")
            terms = request.model_dump(mode="json", include=set(Proposal.model_fields))
            if self.terms is not None and terms != self.terms:
                raise ValueError("idempotency_conflict")
            self.approvals.require(self.request_id, request.approval_ref, terms)
            if self.result:
                return self.result
            if self.terms is None:
                guides = await self.provider.guides(
                    GuideQuery(route_id=request.route_id, date=request.date)
                )
                if not any(
                    g.available
                    and g.guide_id == request.guide_id
                    and request.route_id in g.qualifications
                    for g in guides
                ):
                    raise ValueError("invalid_guide")
                inventory = await self.provider.inventory(
                    InventoryQuery(date=request.date, items=request.equipment)
                )
                if inventory.unavailable or any(
                    inventory.quantities.get(k, 0) < v
                    for k, v in request.equipment.items()
                ):
                    raise ValueError("inventory_conflict")
                self.approvals.require(self.request_id, request.approval_ref, terms)
                self.terms = terms
            result = await self.provider.reserve(request)
            if (
                result.model_dump(mode="json", include=set(Proposal.model_fields))
                != terms
            ):
                raise ValueError("invalid_confirmation")
            self.result = result
            return result

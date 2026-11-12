import asyncio

import httpx
import pytest
from pydantic import ValidationError

from app.models.contracts import BookingRequest, GuideQuery
from app.operator_demo import app
from app.tools.adapters.operator_http import HttpOperatorProvider


def test_operator_http_contract():
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            provider = HttpOperatorProvider("http://demo", client)
            guides = await provider.guides(
                GuideQuery(date="2026-11-12", route_id="PR-PNPE-2")
            )
            assert [g.guide_id for g in guides] == ["ines", "luis"]

    asyncio.run(check())


@pytest.mark.parametrize("reservation_id", [
    "TR-ABCDEFGH", "TR-23456789", "external-provider-existing-reference",
    "d748573e-e51f-40d0-9ddf-26227a2aed1b", "TR-ABCDEFG", "TR-ABCDEFGHI",
    "TR-ABCDEF0H", "TR-ABCDEF1H", "TR-ABCDEFIO", "tr-abcdefgh",
])
def test_external_reservation_uses_shared_short_id_contract(reservation_id):
    async def check():
        from uuid import uuid4

        query = BookingRequest(
            request_id=uuid4(), idempotency_key="booking", approval_ref="approved",
            route_id="trail", date="2026-11-12", guide_id="ines", equipment={},
        )
        receipt = dict(
            route_id=query.route_id, date=query.date.isoformat(), guide_id=query.guide_id,
            equipment={}, reservation_id=reservation_id, status="confirmed",
            created_at="2026-11-12T10:00:00Z",
        )
        transport = httpx.MockTransport(lambda _: httpx.Response(200, json=receipt))
        async with httpx.AsyncClient(transport=transport) as client:
            provider = HttpOperatorProvider("https://operator.example", client)
            if reservation_id in {"TR-ABCDEFGH", "TR-23456789"}:
                assert (await provider.reserve(query)).reservation_id == reservation_id
            else:
                with pytest.raises(ValidationError, match="reservation_id"):
                    await provider.reserve(query)

    asyncio.run(check())

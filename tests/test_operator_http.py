import asyncio

import httpx

from app.models.contracts import GuideQuery
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

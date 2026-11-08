import asyncio
from uuid import uuid4

import pytest

from app.humans.approval import ApprovalRegistry
from app.models.contracts import BookingRequest
from app.tools.operator import MockOperator, OperatorTools


def test_concurrent_duplicate():
    async def run():
        rid = str(uuid4())
        provider = MockOperator({"2026-11-12": ["g"]}, {"poles": 1}, ["trail"])
        registry = ApprovalRegistry()
        ops = OperatorTools(rid, registry, provider)
        terms = dict(
            route_id="trail", guide_id="g", date="2026-11-12", equipment={"poles": 1}
        )

        def request(ref):
            return BookingRequest(
                **terms,
                request_id=rid,
                idempotency_key=f"booking:{rid}",
                approval_ref=ref,
            )

        with pytest.raises(ValueError, match="missing_approval"):
            await ops.reserve(request("forged"))
        arg = request(registry.record(rid, terms, "approved"))
        first, second = await asyncio.gather(ops.reserve(arg), ops.reserve(arg))
        assert first == second and len(provider.created) == 1

    asyncio.run(run())

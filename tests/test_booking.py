import asyncio
from uuid import uuid4
import pytest
from app.models.contracts import BookingRequest
from app.tools.operator import MockOperator
from private_agent_helpers import make_context, scoped


def test_concurrent_duplicate():
    async def run():
        rid = str(uuid4())
        provider = MockOperator({'2026-11-12': ['g']}, {'poles': 1}, ['trail'])
        request = BookingRequest(route_id='trail', guide_id='g', date='2026-11-12',
            equipment={'poles': 1}, request_id=rid, idempotency_key=f'booking:{rid}', approval_ref='approved')
        first, second = await asyncio.gather(provider.reserve(request), provider.reserve(request))
        assert first == second and len(provider.created) == 1
    asyncio.run(run())


def test_preparing_booking_requires_local_exact_approval():
    context = make_context('agent_b')
    terms = dict(route_id='trail', guide_id='g', date='2026-11-12', equipment={})
    state = {'original_proposal': {k:v for k,v in terms.items() if k != 'guide_id'}}
    with scoped(context, state), pytest.raises(ValueError, match='missing_approval'):
        context.prepare_booking(terms)

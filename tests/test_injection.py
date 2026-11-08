import asyncio
import httpx
import pytest
from app.tools.adapters.mock import FailureSchedule


def test_seeded_transient_then_success():
    async def run():
        injection = FailureSchedule(
            {"weather": {"failures": ["timeout", "503", "success"], "latency_ms": 0}},
            42,
        )
        with pytest.raises(TimeoutError):
            await injection.before("weather")
        with pytest.raises(httpx.HTTPStatusError) as error:
            await injection.before("weather")
        assert error.value.response.status_code == 503
        await injection.before("weather")

    asyncio.run(run())

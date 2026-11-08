import asyncio
from collections import defaultdict
import random
import httpx


class FailureSchedule:
    """Apply scenario fault scripts once per provider attempt in a run."""

    def __init__(self, rules, seed):
        self.rules = rules
        self.index = defaultdict(int)
        self.random = random.Random(seed)

    async def before(self, name):
        rule = self.rules.get(name)
        if not rule:
            return
        position = self.index[name]
        self.index[name] += 1
        if rule.get("latency_ms"):
            await asyncio.sleep(rule["latency_ms"] / 1000)
        failures = rule.get("failures", [])
        outcome = failures[position] if position < len(failures) else "success"
        if (
            self.random.random() < rule.get("timeout_probability", 0)
            or outcome == "timeout"
        ):
            raise TimeoutError("Injected timeout")
        if outcome in ("429", "503"):
            response = httpx.Response(
                int(outcome), request=httpx.Request("GET", "https://mock.invalid")
            )
            response.raise_for_status()
        if outcome != "success":
            raise ValueError("Invalid failure script entry")

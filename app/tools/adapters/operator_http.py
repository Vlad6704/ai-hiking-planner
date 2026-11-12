from pydantic import TypeAdapter

from app.models.contracts import Guide, Inventory, Reservation


class HttpOperatorProvider:
    def __init__(self, base_url, client, preset=None):
        if not base_url:
            raise ValueError("Set OPERATOR_URL for real mode")
        self.url = base_url.rstrip("/")
        self.client = client
        self.preset = preset
        self.idempotent_reservations = False

    async def post(self, path, query, schema):
        headers = {}
        if self.preset is not None:
            headers['X-Manual-Preset'] = self.preset.name
            if self.preset.date:
                headers['X-Manual-Preset-Date'] = self.preset.date.isoformat()
        response = await self.client.post(
            self.url + path, json=query.model_dump(mode="json"), headers=headers
        )
        response.raise_for_status()
        if path == "/guides":
            self.idempotent_reservations = (
                response.headers.get("X-Reservation-Idempotency") == "request-id"
            )
        return TypeAdapter(schema).validate_python(response.json())

    async def guides(self, query):
        return await self.post("/guides", query, list[Guide])

    async def inventory(self, query):
        return await self.post("/inventory", query, Inventory)

    async def reserve(self, query):
        return await self.post("/reservations", query, Reservation)

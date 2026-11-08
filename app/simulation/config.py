from pydantic import PositiveFloat, PositiveInt

from app.models.contracts import Contract, Mode


class Settings(Contract):
    mode: Mode = "mock"
    attempts: PositiveInt = 3
    steps: PositiveInt = 100
    exchanges: PositiveInt = 20
    timeout: PositiveFloat = 120
    peer_timeout: PositiveFloat = 30
    tool_timeout: PositiveFloat = 10
    max_weather_age_hours: PositiveFloat = 6

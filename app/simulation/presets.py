"""Session-local synthetic operator conditions shared by mock and HTTP demo."""

from datetime import date as Date
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.tools.operator import MockOperator


class ManualPreset(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    name: Literal['normal', 'no_rain_jackets', 'no_guides_on_date'] = 'normal'
    date: Date | None = None

    @model_validator(mode='after')
    def validate_date(self):
        if (self.name == 'no_guides_on_date') != (self.date is not None):
            raise ValueError('Select a date only for the guide shortage preset')
        return self


def preset_operator(preset, routes):
    stock = dict.fromkeys(['boots', 'water', 'first aid kit', 'warm layer', 'poles'], 4)
    stock['rain jacket'] = 0 if preset.name == 'no_rain_jackets' else 4
    stock['poncho'] = 3
    schedule = {str(preset.date): []} if preset.date else {}
    return MockOperator(schedule, stock, routes, default_guides=['ines', 'luis'])

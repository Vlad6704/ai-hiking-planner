"""Validated timeout overrides shared by automatic and browser sessions."""

from copy import deepcopy
from typing import Literal

from pydantic import Field

from app.models.contracts import Contract

DomainTool = Literal[
    'get_weather_forecast', 'search_hiking_routes', 'get_route_details',
    'get_hiking_equipment', 'check_guide_availability',
    'check_equipment_inventory', 'create_tour_reservation',
]
FAILURE_TOOLS = list(DomainTool.__args__)


class FailureInjection(Contract):
    tool: DomainTool
    timeout_probability: float = Field(ge=0, le=1, allow_inf_nan=False)


def apply_failure_override(case, override):
    case = deepcopy(case)
    if override is not None:
        case.setdefault('failure_injection', {})[override.tool] = {
            'timeout_probability': override.timeout_probability,
        }
        if override.tool == 'get_weather_forecast':
            case['weather_failure'] = False
    return case

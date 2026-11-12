"""Serializable role-local business state and replay-safe collection reducers."""

from copy import deepcopy
from typing import Annotated, NotRequired

from langchain.agents import AgentState


def merge_records(current: dict | None, updates: dict | None) -> dict:
    records = deepcopy(current or {})
    for key, record in (updates or {}).items():
        if key in records and records[key] != record:
            raise ValueError(f'conflicting_record: {key}')
        records[key] = deepcopy(record)
    return records


def merge_statuses(current: dict | None, updates: dict | None) -> dict:
    return {**deepcopy(current or {}), **deepcopy(updates or {})}


class PrivateAgentState(AgentState):
    request_id: str
    inbox: Annotated[dict[str, dict], merge_records]
    outbox: Annotated[dict[str, dict], merge_records]
    observations: Annotated[dict[str, dict], merge_records]
    interactions: Annotated[dict[str, dict], merge_records]
    dispatch_ack: Annotated[dict[str, str], merge_statuses]
    incoming: NotRequired[dict | None]
    trip_status: NotRequired[str]
    pending_interaction: NotRequired[dict | None]
    result: NotRequired[dict | None]


class PlannerState(PrivateAgentState):
    original_proposal: NotRequired[dict | None]
    requirements: NotRequired[dict]
    offer: NotRequired[dict | None]
    customer_reply: NotRequired[dict | None]
    customer_decision: NotRequired[dict | None]
    received_outcome: NotRequired[dict | None]
    booking_progress: NotRequired[dict | None]


class OperatorState(PrivateAgentState):
    original_proposal: NotRequired[dict | None]
    offer: NotRequired[dict | None]
    customer_decision: NotRequired[dict | None]
    selected_guide: NotRequired[str | None]
    approval: NotRequired[dict | None]
    rejections: NotRequired[list[dict]]
    booking: NotRequired[dict | None]
    booking_attempt: NotRequired[dict | None]
    planning_facts: Annotated[dict[str, dict], merge_records]

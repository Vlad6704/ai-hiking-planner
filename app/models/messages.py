"""Validated operational facts exchanged between private agent states."""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, TypeAdapter, model_validator

from app.models.contracts import (
    Contract, Forecast, GearAdvice, GearQuery, Guide, GuideQuery, Inventory, InventoryQuery, Proposal, Reservation,
    RouteLookup, RouteQuery, RouteSummary, Text, ToolResult,
    TripProposal, WeatherQuery,
)


class OperationalRoute(RouteSummary):
    """Route evidence needed for operations, without catalog prose or metadata."""

    elevation_loss_m: int | None = None
    constraints: list[str] = Field(default_factory=list)


class PlanningFact(Contract):
    id: Text
    tool: Literal['get_weather_forecast', 'search_hiking_routes', 'get_route_details', 'get_hiking_equipment']
    query: dict
    result: dict

    @model_validator(mode='after')
    def valid_result(self) -> Self:
        result = ToolResult[object].model_validate(self.result)
        if result.status == 'error':
            raise ValueError('planning_fact_requires_successful_result')
        query_schema, data_schema = {
            'get_weather_forecast': (WeatherQuery, Forecast),
            'search_hiking_routes': (RouteQuery, list[OperationalRoute]),
            'get_route_details': (RouteLookup, OperationalRoute),
            'get_hiking_equipment': (GearQuery, GearAdvice),
        }[self.tool]
        TypeAdapter(query_schema).validate_python(self.query)
        TypeAdapter(data_schema).validate_python(result.data)
        return self


class TripRequestPayload(Contract):
    kind: Literal['trip_request'] = 'trip_request'
    terms: TripProposal
    planning_facts: list[PlanningFact] = Field(default_factory=list)


class TripOfferPayload(Contract):
    kind: Literal['trip_offer'] = 'trip_offer'
    proposal: Proposal


class CustomerDecisionPayload(Contract):
    kind: Literal['customer_decision'] = 'customer_decision'
    offer_message_id: Text
    proposal: Proposal
    decision: Literal['accepted', 'declined']
    interaction_id: Text
    response_event_id: Text
    reply_text: Text
    planning_facts: list[PlanningFact] = Field(default_factory=list)


class OperationalFact(Contract):
    id: Text
    tool: Literal['check_guide_availability', 'check_equipment_inventory']
    query: dict
    result: dict

    @model_validator(mode='after')
    def validate_observation(self) -> Self:
        query_schema, data_schema = {
            'check_guide_availability': (GuideQuery, list[Guide]),
            'check_equipment_inventory': (InventoryQuery, Inventory),
        }[self.tool]
        TypeAdapter(query_schema).validate_python(self.query)
        result = ToolResult[object].model_validate(self.result)
        if result.status != 'error':
            TypeAdapter(data_schema).validate_python(result.data)
        return self


class AvailabilityResultPayload(Contract):
    kind: Literal['availability_result'] = 'availability_result'
    reason: Text
    details: dict = Field(default_factory=dict)
    observations: list[OperationalFact] = Field(default_factory=list)


class ReservationProgressPayload(Contract):
    kind: Literal['reservation_progress'] = 'reservation_progress'
    status: Literal['pending', 'uncertain']
    proposal: Proposal
    idempotency_key: Text


class ReservationOutcomePayload(Contract):
    kind: Literal['reservation_outcome'] = 'reservation_outcome'
    status: Literal['confirmed', 'failed', 'uncertain']
    reservation: Reservation | None = None
    proposal: Proposal | None = None
    approval_ref: Text | None = None
    decision_message_id: Text | None = None
    reason: Text | None = None

    @model_validator(mode='after')
    def valid_confirmation(self) -> Self:
        if self.status == 'confirmed':
            if self.reservation is None or self.approval_ref is None:
                raise ValueError('confirmation_requires_receipt_and_approval')
            if self.proposal is not None and self.proposal.model_dump() != self.reservation.model_dump(
                include=set(Proposal.model_fields)
            ):
                raise ValueError('confirmation_terms_disagree')
        elif self.reservation is not None:
            raise ValueError('unconfirmed_outcome_cannot_carry_reservation')
        return self


class OperationalFailurePayload(Contract):
    kind: Literal['operational_failure'] = 'operational_failure'
    code: Text
    reason: Text


BusinessPayload = Annotated[
    TripRequestPayload | TripOfferPayload | CustomerDecisionPayload | AvailabilityResultPayload
    | ReservationProgressPayload | ReservationOutcomePayload | OperationalFailurePayload,
    Field(discriminator='kind'),
]


class PeerEnvelope(Contract):
    message_id: Text
    request_id: Text
    sender: Literal['agent_a', 'agent_b']
    recipient: Literal['agent_a', 'agent_b']
    correlation_id: Text | None = None
    type: Literal['request', 'response', 'notification', 'error']
    content: str = ''
    timestamp: AwareDatetime
    payload: BusinessPayload | None = None

    @model_validator(mode='after')
    def validate_direction(self) -> Self:
        if self.sender == self.recipient:
            raise ValueError('invalid_message_recipient')
        if self.type in ('response', 'error') and self.correlation_id is None:
            raise ValueError('response_requires_correlation')
        if self.type in ('request', 'notification') and self.correlation_id is not None:
            raise ValueError('unexpected_correlation')
        if self.payload is not None:
            allowed_a = {'trip_request', 'customer_decision', 'operational_failure'}
            allowed_b = {'trip_offer', 'availability_result', 'reservation_progress',
                         'reservation_outcome', 'operational_failure'}
            if self.payload.kind not in (allowed_a if self.sender == 'agent_a' else allowed_b):
                raise ValueError('invalid_sender_payload')
        return self

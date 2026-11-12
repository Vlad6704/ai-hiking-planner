import inspect
import sqlite3
from datetime import datetime
from typing import Literal

from langchain_core.tools import StructuredTool, tool
from langgraph.types import interrupt

from app.models.contracts import (
    BookingRequest,
    GearQuery,
    GuideQuery,
    InventoryQuery,
    Proposal,
    RouteLookup,
    RouteQuery,
    TripSubmission,
    TripProposal,
    WeatherQuery,
)
from app.tools.execution import execute
from app.tools.route_results import route_model_result
from app.tools.planning import (
    fallback_weather,
    gear,
    live_weather,
    mock_forecast,
)


class ApprovedTerms(Proposal):
    """Booking terms already presented to the manager."""


def bind_tools(actor, context):
    @tool
    def ask_human(
        question: str,
        kind: Literal["question", "selection", "approval"] = "question",
        options: list[str] | None = None,
        proposal: Proposal | None = None,
    ):
        """Ask your assigned human. For selection supply available guide IDs in displayed order.
        For approval supply exact route_id, date, guide_id, equipment quantities."""
        if kind == "approval":
            if proposal is None:
                return {"error": "Present exact terms first"}
            try:
                context.validate_manager_proposal(proposal.model_dump(mode="json"))
            except ValueError as exc:
                return {"error": str(exc)}
        data = dict(question=question, kind=kind, options=options or [],
                    proposal=proposal.model_dump(mode='json') if proposal else None)
        data['_source_message_id'] = (context.incoming or {}).get('message_id')
        return context.process_human_reply(data, interrupt(data))

    @tool(return_direct=True)
    async def send_to_agent(
        content: str,
        kind: Literal["request", "response", "notification", "error"] = "notification",
        proposal: Proposal | TripProposal | None = None,
    ):
        """Queue a peer message, then end this turn. A's first operational request requires proposal with
        exact route_id, date and equipment quantities; omit guide_id until the manager selects it.
        Include the full proposal for exact revised offers. A returns customer decisions with reply_with_customer_decision.
        B must verify substitute inventory before offering it. A must obtain explicit customer consent then return the decision."""
        try:
            return context.stage_message(content, kind, proposal)
        except ValueError as exc:
            return {'error': str(exc)}

    @tool(return_direct=True)
    def reply_with_customer_decision(decision: Literal["accepted", "declined"]):
        """Interpret the customer's reply to the current exact offer and return their decision to B.
        Use only for clear acceptance or refusal. Clarify ambiguity or request changed terms first."""
        try:
            return context.reply_with_customer_decision(decision)
        except ValueError as exc:
            return {"error": str(exc)}

    @tool(return_direct=True)
    def acknowledge_message():
        """End your turn after a message from the OTHER AGENT that requires no further action.
        Sends nothing. NEVER use for customer or manager messages, greetings, questions, or answers."""
        context.trace.emit('agent.acknowledged', actor, {})
        return {'acknowledged': True}

    @tool
    def send_to_customer(content: str):
        """Show an informational answer to the customer and wait for their next message. Does not book or finish the trip. Use for route listings and other informational replies."""
        if (context.state.get('received_outcome') or {}).get('status') == 'confirmed':
            return {'error': 'A reservation exists; deliver its validated final result using submit_trip_result.'}
        if context.has_pending_request:
            return {'error': 'Resolve the outstanding operator request before waiting for another customer message.'}
        data = dict(question=content, kind='information', options=[], proposal=None)
        return context.process_human_reply(data, interrupt(data))

    def domain(name, description, schema, function):
        async def invoke(**kwargs):
            query = schema(**kwargs)
            catalog_state = None
            catalog_error = None
            if name in ("search_hiking_routes", "get_route_details"):
                try:
                    catalog_state = await context.catalog.ensure_fresh()
                except (ValueError, OSError, sqlite3.Error) as exc:
                    catalog_error = str(exc)
                finally:
                    if context.catalog.last_report:
                        context.trace.emit("catalog.refreshed", actor, context.catalog.last_report)
                        context.catalog.last_report = None

            async def call():
                if catalog_error:
                    raise ValueError(catalog_error)
                if context.settings.mode == "mock":
                    await context.injection.before(name)
                value = function(query)
                return await value if inspect.isawaitable(value) else value

            fallback = None
            if (
                name == "get_weather_forecast"
                and context.settings.mode == "mock"
                and context.case["fallback"]
            ):
                fallback = lambda: fallback_weather(
                    context.forecast,
                    query,
                    datetime.fromisoformat(context.case["clock"]),
                    context.settings.max_weather_age_hours,
                )
            result = await execute(
                name,
                query.model_dump(mode="json"),
                call,
                context.settings,
                context.trace,
                actor,
                fallback,
                metadata={"catalog": catalog_state} if catalog_state else None,
            )
            context.record_observation(name, query.model_dump(mode='json'), result)
            if name in ("search_hiking_routes", "get_route_details"):
                return route_model_result(result, details=name == "get_route_details")
            return result

        return StructuredTool.from_function(
            coroutine=invoke, name=name, description=description, args_schema=schema
        )

    async def weather(query):
        if context.settings.mode == "real":
            return await live_weather(context.client, query)
        if context.case["weather_failure"]:
            raise TimeoutError()
        return mock_forecast(context.forecast, query)

    def routes(query):
        return context.catalog.store.search(query)

    def route_details(query):
        return context.catalog.store.details(query.route_id)

    async def book(terms):
        return await context.reserve(terms)

    @tool
    async def submit_trip_result(result: TripSubmission):
        """Deliver status and exact business terms, or the failure reason.
        Runtime binds request and reservation IDs from trusted state and renders the final message."""
        try:
            terminal = context.make_result(result)
            await context.deliver_final(terminal)
            context.state['result'] = terminal.model_dump(mode='json')
        except ValueError as exc:
            return {"error": str(exc)}
        return "Delivered"

    @tool("ask_human")
    def ask_customer(question: str, proposal: Proposal | None = None):
        """Ask the hiker a question. For revised terms include the exact operator-offered proposal.
        Interpret their reply and use reply_with_customer_decision for clear acceptance or refusal."""
        terms = proposal.model_dump(mode="json") if proposal else None
        if terms is not None and (not context.state.get('offer') or context.state['offer']["proposal"] != terms):
            return {"error": "Present the exact operator-offered substitution"}
        data = dict(question=question, kind='substitution' if proposal else 'question', options=[], proposal=terms)
        data['_source_message_id'] = (context.incoming or {}).get('message_id')
        data['_original_proposal'] = context.state.get('original_proposal')
        return context.process_human_reply(data, interrupt(data))

    shared = [ask_customer if actor == "agent_a" else ask_human, send_to_agent, acknowledge_message]
    if actor == "agent_a":
        return shared + [
            reply_with_customer_decision,
            send_to_customer,
            domain(
                "get_weather_forecast",
                "Forecast for Picos de Europa and an ISO date or range.",
                WeatherQuery,
                weather,
            ),
            domain(
                "search_hiking_routes",
                "Search route variants. All filters are optional. Keywords are literal source-language terms (primarily Spanish). A page mention does not establish a feature on every variant. Preserve the exact returned route_id.",
                RouteQuery,
                routes,
            ),
            domain(
                "get_route_details",
                "Look up a route by exact ID.",
                RouteLookup,
                route_details,
            ),
            domain(
                "get_hiking_equipment",
                "Get required and missing gear for route, forecast day and duration.",
                GearQuery,
                gear,
            ),
            submit_trip_result,
        ]
    return shared + [
        domain(
            "check_guide_availability",
            "List qualified available guides.",
            GuideQuery,
            context.provider.guides,
        ),
        domain(
            "check_equipment_inventory",
            "Check quantities of rental items.",
            InventoryQuery,
            context.provider.inventory,
        ),
        domain(
            "create_tour_reservation",
            "Create the reservation for the exact manager-approved route, date, guide and equipment.",
            ApprovedTerms,
            book,
        ),
    ]

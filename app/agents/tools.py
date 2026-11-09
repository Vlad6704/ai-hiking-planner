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
    TripResult,
    WeatherQuery,
)
from app.tools.execution import execute
from app.tools.planning import (
    details,
    fallback_weather,
    gear,
    live_weather,
    search,
    select_forecast,
)


class ApprovedTerms(Proposal):
    """Booking terms already presented to the manager."""


def bind_tools(run, actor):
    @tool
    def ask_human(
        question: str,
        kind: Literal["question", "selection", "approval"] = "question",
        options: list[str] | None = None,
        proposal: Proposal | None = None,
    ):
        """Ask your assigned human. For selection supply available guide IDs in displayed order.
        For approval supply exact route_id, date, guide_id, equipment quantities."""
        return interrupt(
            dict(
                question=question,
                kind=kind,
                options=options or [],
                proposal=proposal.model_dump(mode="json") if proposal else None,
            )
        )

    @tool(return_direct=True)
    async def send_to_agent(
        content: str,
        kind: Literal["request", "response", "notification", "error"] = "request",
    ):
        """Queue a message to the other agent. End this turn after sending."""
        parent = run.incoming.get(actor)
        if parent and parent["message_id"] in run.bus.pending:
            kind = "error" if kind == "error" else "response"
        elif actor == "agent_b" and run.operator.result:
            # A completed operator sends the reservation for delivery. The
            # customer-facing agent owes no further peer reply for this notice.
            kind = "notification"
        elif kind != "notification":
            # Replies always close the request that woke this agent. The next
            # exchange can then carry a revised proposal as a fresh request.
            if parent and parent["type"] == "request" and kind in ("response", "error"):
                return {"error": "This request is already closed."}
            else:
                kind = "request"
        receipt = run.bus.send(actor, content, kind, parent)
        return {"queued": receipt["message_id"]}

    def domain(name, description, schema, function):
        async def invoke(**kwargs):
            query = schema(**kwargs)
            catalog_state = None
            catalog_error = None
            if run.settings.mode == "real" and name in ("search_hiking_routes", "get_route_details"):
                try:
                    catalog_state = await run.catalog.ensure_fresh()
                except (ValueError, OSError, sqlite3.Error) as exc:
                    catalog_error = str(exc)
                finally:
                    if run.catalog.last_report:
                        run.trace.emit("catalog.refreshed", actor, run.catalog.last_report)
                        run.catalog.last_report = None

            async def call():
                if catalog_error:
                    raise ValueError(catalog_error)
                if run.settings.mode == "mock":
                    await run.injection.before(name)
                value = function(query)
                return await value if inspect.isawaitable(value) else value

            fallback = None
            if (
                name == "get_weather_forecast"
                and run.settings.mode == "mock"
                and run.case["fallback"]
            ):
                fallback = lambda: fallback_weather(
                    run.forecast,
                    query,
                    datetime.fromisoformat(run.case["clock"]),
                    run.settings.max_weather_age_hours,
                )
            result = await execute(
                name,
                query.model_dump(mode="json"),
                call,
                run.settings,
                run.trace,
                actor,
                fallback,
                metadata={"catalog": catalog_state} if catalog_state else None,
            )
            if result["status"] != "error":
                run.observed.setdefault(name, []).append(result["data"])
            return result

        return StructuredTool.from_function(
            coroutine=invoke, name=name, description=description, args_schema=schema
        )

    async def weather(query):
        if run.settings.mode == "real":
            return await live_weather(run.client, query)
        if run.case["weather_failure"]:
            raise TimeoutError()
        return select_forecast(run.forecast, query)

    def routes(query):
        return run.catalog.store.search(query) if run.settings.mode == "real" else search(query)

    def route_details(query):
        return run.catalog.store.details(query.route_id) if run.settings.mode == "real" else details(query.route_id)

    async def book(terms):
        for alternatives in run.case["required_rentals"]:
            if not any(terms.equipment.get(item, 0) >= 1 for item in alternatives):
                raise ValueError(
                    "Missing required rental: " + " or ".join(alternatives)
                )
        days = [
            day
            for report in run.observed.get("get_weather_forecast", [])
            for day in report["days"]
            if day["date"] == str(terms.date)
        ]
        if (
            not days
            or days[-1]["wind_kmh"] > 40
            or days[-1]["precipitation_probability"] > 70
        ):
            raise ValueError("A verified safe forecast is required for this date")
        if not any(
            route["route_id"] == terms.route_id
            for routes in run.observed.get("search_hiking_routes", [])
            for route in routes
        ):
            raise ValueError("A verified route is required")
        active = run.approvals.records.get(run.rid)
        if active is None:
            raise ValueError("missing_approval")
        request = BookingRequest(
            **terms.model_dump(),
            request_id=run.rid,
            idempotency_key=f"booking:{run.rid}",
            approval_ref=active[0],
        )
        return await run.operator.reserve(request)

    @tool
    async def submit_trip_result(result: TripResult, final_message: str):
        """Deliver the terminal result. For failure send the exact reason. For confirmation use exactly:
        Confirmed {route_id} on {date} with {guide_id}. Reservation {reservation_id}. Equipment: {items}.
        Join sorted equipment with comma-space or use none."""
        try:
            await run.finalize(result, final_message)
        except ValueError as exc:
            return {"error": str(exc)}
        return "Delivered"

    @tool("ask_human")
    def ask_customer(question: str):
        """Ask the hiker a question about dates, experience, route preferences or owned gear."""
        return interrupt(
            dict(question=question, kind="question", options=[], proposal=None)
        )

    shared = [ask_customer if actor == "agent_a" else ask_human, send_to_agent]
    if actor == "agent_a":
        return shared + [
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
            run.provider.guides,
        ),
        domain(
            "check_equipment_inventory",
            "Check quantities of rental items.",
            InventoryQuery,
            run.provider.inventory,
        ),
        domain(
            "create_tour_reservation",
            "Create the reservation for the exact manager-approved route, date, guide and equipment.",
            ApprovedTerms,
            book,
        ),
    ]

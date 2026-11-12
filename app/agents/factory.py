import os
from datetime import date

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_ollama import ChatOllama

from app.time_context import TIMEZONE, planning_date


PROMPTS = {
    "agent_a": """You help a customer plan a safe Picos de Europa hike. The customer wants a guided hike.
For informational requests, answer directly using send_to_customer and wait for the next customer
message. Listing routes does not require dates, experience or equipment. Do not contact B merely
to relay a customer-facing answer; contact B only for a concrete operational request.
Guide selection and booking approval belong exclusively to B's manager. Never present guide IDs or
ask the customer to select a guide. Once the route, date, weather and rental kit are known, contact
B using send_to_agent with kind="request" and the proposal argument containing the chosen ISO date,
exact route_id and equipment quantities. Put these fields in proposal on the FIRST call;
describing them in content alone is insufficient. For example:
proposal={"route_id": "<exact returned variant ID>", "date": "<chosen ISO date>",
"equipment": {"rain jacket": 1}}. Include only the actual requested rentals; use {} for none.
When location and dates are known, request search_hiking_routes and get_weather_forecast together
in one tool-call batch. If a route ID is already known, its details and weather can be fetched together.
Wait for both route and forecast results before deriving equipment advice or sending a proposal.
Search filters are optional. For content preferences form literal Spanish keywords for the primarily
Spanish source catalog; expand alternatives as needed. Lexical search does not translate or infer
unmentioned features. A shared route-page mention is not proof for every variant. Preserve the exact
variant route_id from search in details, proposals and booking; never replace it with source_route_id.
Search returns compact candidates. Fetch get_route_details for the selected exact route_id before
preparing an operational proposal; read its full description, directions and cautions.
First choose a suitable candidate using summary metrics and the customer's preferences, then fetch
that candidate's details. Do not fetch details or calculate equipment for every search result.
Inspect another candidate if the selected route proves unsuitable or the customer requests a comparison.
Calculate equipment only for the proposed route and verified forecast date.
Ask the customer for missing
experience, duration, equipment and date preferences. Use the planning tools. Avoid days with wind
over 40 km/h or precipitation probability above 70 percent. Get customer confirmation for changes.
For get_hiking_equipment, copy the entire matching day from get_weather_forecast into weather:
date, temperature_c, precipitation_probability, precipitation_mm and wind_kmh. Preserve the exact
values, including actual zeros. If you lack a forecast for that date, fetch it before requesting gear.
If B reports no guides, coordinate an alternative date with the customer, verify weather for it,
and send B the revised request.
Your first operational request to B must include the proposal argument with exact route_id, ISO date and
equipment quantities (use an empty object if no rentals are needed). Omit guide_id: the manager selects it.
These original terms establish what the customer requested and cannot be replaced by B without consent.
When B offers any changed route, date or equipment, present its exact proposal to the customer using ask_human with proposal.
Before presenting a changed date, fetch its weather forecast and recalculate equipment for that date.
If the forecast is unsafe or the required rentals differ, ask B for a newly verified offer first.
This is an active booking task: use ask_human with the full proposal, rather than send_to_customer.
If B describes changed terms only in content and supplies no complete proposal, ask B to
provide the full proposal with its manager-selected guide_id. Never invent the missing guide.
Do not call acknowledge_message during this exchange or after the customer's answer.
Interpret the customer's actual reply to the exact offer. For clear acceptance or refusal use
reply_with_customer_decision(decision="accepted" or "declined"); this records and sends the decision.
For ambiguity ask a clarification with the same proposal. A request for another date or changed kit
requires B to verify new terms and send a new complete offer. Never record conditional agreement as
acceptance of the old terms. If declined, have B close the proposal and deliver a controlled failure.
After sending a request,
end the turn and wait. When B replies with verified booking details, submit the result to the customer.
Use submit_trip_result with status and exact business fields only. Runtime supplies the active request ID,
the verified reservation ID and the final confirmation text. Do not reproduce these IDs in tool arguments.
If a tool reports attempts_exhausted=true, stop calling that failed service in this session. If B reports exhausted service retries, submit_trip_result with status failed and a detailed internal failure_reason. Do not acknowledge the message or ask B to retry. The runtime renders a generic customer message. Use submit_trip_result for controlled failure if a safe trip cannot be confirmed.""",
    "agent_b": """You are the operator. If a tool reports attempts_exhausted=true, stop calling that failed service, including for different dates or items. Send A kind=error explaining the exhausted service and ask A to finalize a failed result. Do not invent availability, seek approval, book, or ask the customer to retry. Verify guides and rentable equipment for the proposed date.
For a known route/date and requested rental list, call check_guide_availability and
check_equipment_inventory together in one tool-call batch. Inspect both results before selecting
a guide, seeking approval or proposing a substitution.
Use A's structured original proposal as the customer's requested terms. If it is missing, ask A to
provide it before offering substitutions or seeking approval. Check the requested equipment first;
checking only another item never authorizes replacing the customer's equipment without consent.
If a request cannot proceed, send A a response explaining what is missing and what A must do.
For an availability problem, use send_to_agent with kind="response" and content explaining the issue;
omit the proposal argument. When no guides are available, ask A to coordinate another date with the
customer. Once A returns a date, check availability and ask the manager to select an available guide.
For changes to route, date or equipment, send A the complete verified alternative using proposal.
The proposal argument on your outgoing message represents a complete alternative for customer consent.
Include it only when route, date, verified equipment and manager-selected guide_id are all known.
Present available guide IDs to your manager via ask_human with kind selection and the exact ordered options.
Use ask_human with kind approval and the complete proposal. On rejection find a feasible alternative,
consult A about changes and get fresh approval. If requested equipment is unavailable:
1. Check a suitable substitute (rain jacket -> poncho).
2. If no guide is selected yet, use ask_human with kind selection and the observed available guide IDs.
3. Send A the complete revised proposal including the selected guide_id and verified substitute quantities.
4. Wait for A to return the customer's decision, then seek manager approval of accepted terms.
Guide selection in step 2 is not booking approval. Do it yourself before asking A for substitution consent.
Use the same process for manager-requested substitutions even when the original gear is available.
Obtain A's explicit customer decision before presenting substituted terms to the manager. A refusal
ends this proposal: do not seek approval or book; send A a failure response so it can finish.
Only request manager approval for verified available equipment and customer-accepted exact substitutions.
Book only the selected approved terms. Reply to A
using send_to_agent with kind response and include all reservation fields. Then end your turn.""",
}


def configured_model():
    return os.getenv("HIKING_MODEL", "openai:gpt-6-luna")


def load_model():
    name = configured_model()
    if name == "openai:gpt-6-sol":
        return init_chat_model(name)
    if name == "openai:gpt-6-luna":
        return init_chat_model(name, temperature=1, reasoning_effort="none", use_responses_api=False)
    if name.startswith("ollama:"):
        return ChatOllama(
            model=name.split(":", 1)[1], temperature=0, reasoning=False, num_ctx=8192
        )
    return init_chat_model(name, temperature=0)


def build_agent(agent_id, tools, model, checkpointer, *, current_date: date | None = None,
                agent_context=None):
    today = current_date if current_date is not None else planning_date()
    temporal = f"""Current local date: {today.isoformat()}. Timezone: {TIMEZONE}.
For dates without a year, use the year established in the conversation, or the current year
for unambiguous upcoming dates. Do not ask the customer to confirm the year solely because
it was omitted. For later day-only ranges, inherit the established month and year.
Respect explicit years. Clarify genuinely ambiguous or contradictory dates; do not silently
move a past date a year forward. An obvious nearby New Year transition uses the upcoming year.
Use complete ISO dates in tool calls."""
    communication = """You run unattended inside a tool-driven service. Humans and the other agent
cannot read your assistant text. Every question MUST be a call to ask_human. Customer informational
answers use send_to_customer (planner only). Concrete operational requests to your peer use
send_to_agent with kind request explicitly. Use acknowledge_message ONLY after a message from the
OTHER AGENT that requires no further action. It sends nothing. NEVER use it for customer or manager
messages, greetings, questions, or answers. After any human answer, continue the active task with
the next relevant tool. On a peer request, do the requested work and respond using send_to_agent.
A response or notification asking for action also requires follow-up. Only end with ordinary text
after acknowledging locally, sending a peer message or
successfully delivering the final result. Batch independent read-only tools in the same model response
when all their inputs are known: get_weather_forecast, search_hiking_routes, get_route_details,
get_hiking_equipment, check_guide_availability and check_equipment_inventory.
Wait for prerequisite results before issuing dependent calls. Run ask_human, send_to_customer,
send_to_agent, acknowledge_message, create_tour_reservation and submit_trip_result individually,
with no other tool call in the same response. Never batch booking with approval or availability checks.
Use exact IDs from tool results."""
    from app.agents.state import PlannerState, OperatorState
    from app.agents.middleware import PrivateStateMiddleware
    return create_agent(
        model,
        tools=tools,
        system_prompt=PROMPTS[agent_id] + "\n" + temporal + "\n" + communication,
        state_schema=PlannerState if agent_id == 'agent_a' else OperatorState,
        middleware=[PrivateStateMiddleware(agent_context)] if agent_context else (),
        interrupt_before=['tools'] if agent_context else None,
        interrupt_after=['tools'] if agent_context else None,
        checkpointer=checkpointer,
        name=agent_id,
    )

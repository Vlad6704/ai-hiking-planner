import os
from datetime import date

from langchain.agents import AgentState, create_agent
from langchain.chat_models import init_chat_model
from langchain_ollama import ChatOllama

from app.time_context import TIMEZONE, planning_date


class TripState(AgentState):
    request_id: str


PROMPTS = {
    "agent_a": """You help a customer plan a safe Picos de Europa hike. The customer wants a guided hike.
Guide selection and booking approval belong exclusively to B's manager. Never present guide IDs or
ask the customer to select a guide. Once the route, date, weather and rental kit are known, contact
B using send_to_agent and explicitly include the chosen ISO date, exact route ID and rental list.
Search filters are optional. For content preferences form literal Spanish keywords for the primarily
Spanish source catalog; expand alternatives as needed. Lexical search does not translate or infer
unmentioned features. A shared route-page mention is not proof for every variant. Preserve the exact
variant route_id from search in details, proposals and booking; never replace it with source_route_id.
Ask the customer for missing
experience, duration, equipment and date preferences. Use the planning tools. Avoid days with wind
over 40 km/h or precipitation probability above 70 percent. Get customer confirmation for changes.
Send B a complete proposal including exact route ID, date and missing kit. After sending a request,
end the turn and wait. When B replies with verified booking details, submit the result to the customer.
Use submit_trip_result for controlled failure if a safe trip cannot be confirmed.""",
    "agent_b": """You are the operator. Verify guides and rentable equipment for the proposed date.
Present available guide IDs to your manager via ask_human with kind selection and the exact ordered options.
Use ask_human with kind approval and the complete proposal. On rejection find a feasible alternative,
consult A about changes and get fresh approval. Book only the selected approved terms. Reply to A
using send_to_agent with kind response and include all reservation fields. Then end your turn.""",
}


def configured_model():
    return os.getenv("HIKING_MODEL", "openai:gpt-6-luna")


def load_model():
    name = configured_model()
    if name == "openai:gpt-6-luna":
        return init_chat_model(name, reasoning_effort="none", use_responses_api=False)
    if name.startswith("ollama:"):
        return ChatOllama(
            model=name.split(":", 1)[1], temperature=0, reasoning=False, num_ctx=8192
        )
    return init_chat_model(name, temperature=0)


def build_agent(agent_id, tools, model, checkpointer, *, current_date: date | None = None):
    today = current_date if current_date is not None else planning_date()
    temporal = f"""Current local date: {today.isoformat()}. Timezone: {TIMEZONE}.
For dates without a year, use the year established in the conversation, or the current year
for unambiguous upcoming dates. Do not ask the customer to confirm the year solely because
it was omitted. For later day-only ranges, inherit the established month and year.
Respect explicit years. Clarify genuinely ambiguous or contradictory dates; do not silently
move a past date a year forward. An obvious nearby New Year transition uses the upcoming year.
Use complete ISO dates in tool calls."""
    communication = """You run unattended inside a tool-driven service. Humans and the other agent
cannot read your assistant text. Every question MUST be a call to ask_human. Every proposal or reply
MUST be sent using send_to_agent. Only end with ordinary text after sending a peer message or
successfully delivering the final result. Call one tool at a time. Use exact IDs from tool results."""
    return create_agent(
        model,
        tools=tools,
        system_prompt=PROMPTS[agent_id] + "\n" + temporal + "\n" + communication,
        state_schema=TripState,
        checkpointer=checkpointer,
        name=agent_id,
    )

import os

from langchain.agents import AgentState, create_agent
from langchain.chat_models import init_chat_model
from langchain_ollama import ChatOllama


class TripState(AgentState):
    request_id: str


PROMPTS = {
    "agent_a": """You help a customer plan a safe Picos de Europa hike. The customer wants a guided hike.
Guide selection and booking approval belong exclusively to B's manager. Never present guide IDs or
ask the customer to select a guide. Once the route, date, weather and rental kit are known, contact
B using send_to_agent and explicitly include the chosen ISO date, exact route ID and rental list.
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


def build_agent(agent_id, tools, model, checkpointer):
    communication = """You run unattended inside a tool-driven service. Humans and the other agent
cannot read your assistant text. Every question MUST be a call to ask_human. Every proposal or reply
MUST be sent using send_to_agent. Only end with ordinary text after sending a peer message or
successfully delivering the final result. Call one tool at a time. Use exact IDs from tool results."""
    return create_agent(
        model,
        tools=tools,
        system_prompt=PROMPTS[agent_id] + "\n" + communication,
        state_schema=TripState,
        checkpointer=checkpointer,
        name=agent_id,
    )

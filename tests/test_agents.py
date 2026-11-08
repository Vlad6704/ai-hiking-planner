from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.factory import build_agent


def test_bound_tools_and_thread_isolation():
    model = ChatOllama(model="gemma4:26b")
    a = build_agent("agent_a", [], model, InMemorySaver())
    b = build_agent("agent_b", [], model, InMemorySaver())
    assert a is not b and a.checkpointer is not b.checkpointer

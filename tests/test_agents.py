from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.factory import build_agent


def test_bound_tools_and_thread_isolation():
    model = ChatOllama(model="gemma4:26b")
    a = build_agent("agent_a", [], model, InMemorySaver())
    b = build_agent("agent_b", [], model, InMemorySaver())
    assert a is not b and a.checkpointer is not b.checkpointer


def test_default_luna_and_ollama_selection(monkeypatch):
    from app.agents.factory import configured_model, load_model

    monkeypatch.delenv("HIKING_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-only")
    assert configured_model() == "openai:gpt-6-luna"
    luna = load_model()
    assert luna.model_name == "gpt-6-luna" and luna.reasoning_effort == "none"
    monkeypatch.setenv("HIKING_MODEL", "ollama:gemma4:26b")
    assert load_model().model == "gemma4:26b"

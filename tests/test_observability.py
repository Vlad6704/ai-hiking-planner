from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.observability.langsmith import Usage


def test_token_counts():
    usage = Usage()
    usage.on_llm_end(
        LLMResult(
            generations=[
                [
                    ChatGeneration(
                        message=AIMessage(
                            content="yes",
                            usage_metadata={
                                "input_tokens": 5,
                                "output_tokens": 2,
                                "total_tokens": 7,
                            },
                        )
                    )
                ]
            ]
        )
    )
    assert usage.calls == 1 and usage.input_tokens == 5 and usage.output_tokens == 2

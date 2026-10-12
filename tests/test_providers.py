"""The Claude and Gemini clients, with their SDKs mocked (no network)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent import llm
from agent.llm import MAX_TOKENS, ClaudeProvider, GeminiProvider
from agent.planner import PLAN_SCHEMA

SYSTEM = ["fixed instructions", "Context: {}"]
PLAN_JSON = '{"blocks":[{"task_id":1,"start":"2026-10-12T09:00",' \
            '"end":"2026-10-12T10:00"}]}'


def block(**fields):
    return SimpleNamespace(**fields)


# ---------- Claude ----------

def claude_provider(response):
    provider = ClaudeProvider.__new__(ClaudeProvider)
    provider.client = MagicMock()
    provider.client.messages.create.return_value = response
    provider.model = "claude-haiku-5-5"
    provider.effort = "medium"
    return provider


def claude_response(content, stop_reason="end_turn", cache_read=0):
    return SimpleNamespace(
        content=content, stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=80, output_tokens=8,
                              cache_creation_input_tokens=0,
                              cache_read_input_tokens=cache_read),
    )


@pytest.mark.parametrize("name, cls", [
    (None, ClaudeProvider), ("claude", ClaudeProvider),
    ("gemini", GeminiProvider),
])
def test_get_provider_follows_llm_provider(monkeypatch, name, cls):
    monkeypatch.setattr(llm, "_provider", None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    if name is None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("LLM_PROVIDER", name)

    assert isinstance(llm.get_provider(), cls)


def test_claude_asks_for_json_and_parses_it():
    content = [block(type="thinking", thinking="", signature="sig"),
               block(type="text", text=PLAN_JSON)]
    provider = claude_provider(claude_response(content, cache_read=500))
    history = []
    provider.add_user_message(history, "plan my week")

    reply, usage = provider.respond(history, SYSTEM, PLAN_SCHEMA)

    assert reply["blocks"][0]["task_id"] == 1
    # The assistant turn is appended exactly as returned (thinking too).
    assert history[-1] == {"role": "assistant", "content": content}
    kwargs = provider.client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-5-5"
    assert kwargs["max_tokens"] == MAX_TOKENS
    assert kwargs["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": PLAN_SCHEMA},
    }
    assert "tools" not in kwargs
    assert kwargs["system"][0] == {"type": "text", "text": "fixed instructions",
                                   "cache_control": {"type": "ephemeral"}}
    # Cached input counts toward input tokens for the budget.
    assert usage == {"input_tokens": 580, "output_tokens": 8}


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_claude_refusal_and_cutoff_are_errors(stop_reason):
    provider = claude_provider(claude_response([], stop_reason))

    with pytest.raises(RuntimeError):
        provider.respond([], SYSTEM, PLAN_SCHEMA)


# ---------- Gemini ----------

def gemini_provider(text):
    provider = GeminiProvider.__new__(GeminiProvider)
    provider.client = MagicMock()
    provider.client.models.generate_content.return_value = SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(prompt_token_count=90,
                                       candidates_token_count=20,
                                       thoughts_token_count=5),
    )
    provider.model = "gemini-test"
    return provider


def test_gemini_asks_for_json_and_parses_it():
    provider = gemini_provider(PLAN_JSON)
    history = []
    provider.add_user_message(history, "plan my week")

    reply, usage = provider.respond(history, SYSTEM, PLAN_SCHEMA)

    assert reply["blocks"][0]["task_id"] == 1
    assert history == [
        {"role": "user", "parts": [{"text": "plan my week"}]},
        {"role": "model", "parts": [{"text": PLAN_JSON}]},
    ]
    kwargs = provider.client.models.generate_content.call_args.kwargs
    assert kwargs["model"] == "gemini-test"
    assert kwargs["config"]["system_instruction"] == \
        "fixed instructions\n\nContext: {}"
    assert kwargs["config"]["response_mime_type"] == "application/json"
    assert kwargs["config"]["response_json_schema"] == PLAN_SCHEMA
    assert usage == {"input_tokens": 90, "output_tokens": 25}


def test_gemini_empty_reply_is_an_error():
    with pytest.raises(RuntimeError):
        gemini_provider("").respond([], SYSTEM, PLAN_SCHEMA)

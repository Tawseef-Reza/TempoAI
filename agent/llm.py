"""The model behind TempoAI: Claude Haiku by default, or Gemini
(LLM_PROVIDER=gemini) for testing.

Both take the conversation history, the system prompt ([fixed
instructions, context]) and a JSON schema, and return (parsed JSON reply,
usage). The history is kept in each SDK's own message format.
"""

import json
import os

DEFAULT_CLAUDE_MODEL = "claude-haiku-5-5"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
# Caps the cost of any single call (thinking counts as output).
MAX_TOKENS = 8000


class ClaudeProvider:

    def __init__(self):
        import anthropic

        # Credentials come from ANTHROPIC_API_KEY.
        self.client = anthropic.Anthropic()
        self.model = os.getenv("CLAUDE_MODEL") or DEFAULT_CLAUDE_MODEL
        self.effort = os.getenv("CLAUDE_EFFORT") or "medium"

    def add_user_message(self, history, text):
        history.append({"role": "user", "content": text})

    def respond(self, history, system, schema):
        instructions, context = system
        response = self.client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            # Fixed instructions first, marked for caching.
            system=[
                {"type": "text", "text": instructions,
                 "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": context},
            ],
            messages=history,
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        )
        # Appended exactly as returned (thinking blocks included).
        history.append({"role": "assistant", "content": response.content})

        usage = response.usage
        tokens = {
            "input_tokens": usage.input_tokens
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
            + (getattr(usage, "cache_read_input_tokens", 0) or 0),
            "output_tokens": usage.output_tokens,
        }
        if response.stop_reason == "refusal":
            raise RuntimeError("the model declined this request")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("the reply was cut off, please try again")
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text), tokens


class GeminiProvider:

    def __init__(self):
        from google import genai

        # Credentials come from GEMINI_API_KEY.
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.model = os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL

    def add_user_message(self, history, text):
        history.append({"role": "user", "parts": [{"text": text}]})

    def respond(self, history, system, schema):
        response = self.client.models.generate_content(
            model=self.model,
            contents=history,
            config={
                "system_instruction": "\n\n".join(system),
                "response_mime_type": "application/json",
                "response_json_schema": schema,
                "max_output_tokens": MAX_TOKENS,
            },
        )
        text = response.text or ""
        history.append({"role": "model", "parts": [{"text": text}]})

        meta = response.usage_metadata
        tokens = {
            "input_tokens": getattr(meta, "prompt_token_count", 0) or 0,
            "output_tokens": (getattr(meta, "candidates_token_count", 0) or 0)
            + (getattr(meta, "thoughts_token_count", 0) or 0),
        }
        if not text:
            raise RuntimeError("no reply from the model, please try again")
        return json.loads(text), tokens


_provider = None


def get_provider():
    global _provider
    if _provider is None:
        name = (os.getenv("LLM_PROVIDER") or "claude").lower()
        _provider = GeminiProvider() if name == "gemini" else ClaudeProvider()
    return _provider

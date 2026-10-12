from types import SimpleNamespace

import pytest

import config
import database.db as db
from agent import llm

USAGE = {"input_tokens": 100, "output_tokens": 10}


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Keep every test out of the real data/tempo.db, with no usage limits
    whatever .env says."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "AI_LIMITS_ENABLED", False)
    db.use_session_db(None)
    db.init_db()


# ---------- fake model ----------

def reply(*blocks):
    """A fake model reply: reply((task_id, start, end), ...)."""
    return {"blocks": [
        {"task_id": task_id, "start": start.isoformat(),
         "end": end.isoformat()}
        for task_id, start, end in blocks
    ]}


class ScriptedProvider:
    """Stands in for Claude/Gemini: returns canned replies in order and
    records every request."""

    def __init__(self):
        self.script = []
        self.requests = []

    def add_user_message(self, history, text):
        history.append({"role": "user", "text": text})

    def respond(self, history, system, schema):
        self.requests.append({
            "contents": list(history), "system": system, "schema": schema,
        })
        answer = self.script.pop(0)
        history.append({"role": "assistant", "reply": answer})
        return answer, USAGE


@pytest.fixture
def scripted_llm(monkeypatch):
    provider = ScriptedProvider()
    monkeypatch.setattr(llm, "get_provider", lambda: provider)
    return SimpleNamespace(script=provider.script,
                           requests=provider.requests)

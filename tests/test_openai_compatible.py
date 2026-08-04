import sys
from types import SimpleNamespace

from meeting_notes.ai_summarizer import OpenAICompatibleSummarizer


def test_openai_compatible_summarizer_uses_exact_endpoint_model_and_optional_key(monkeypatch):
    """Custom providers share Ollama Cloud's chat-completions contract."""
    constructed = {}
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
                choices=[SimpleNamespace(message=SimpleNamespace(content="""
TITLE:
Gateway Test
OVERVIEW:
Works.
KEY POINTS:
- Endpoint received the configured model
ACTION ITEMS:
None identified
DECISIONS:
None identified
PARTICIPANTS:
None
"""))],
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            constructed.update(kwargs)
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    summarizer = OpenAICompatibleSummarizer(
        api_key="gateway-key",
        model="acme/meeting-model",
        base_url="https://gateway.example.test/v1/",
        provider_name="Acme Gateway",
    )
    summary = summarizer.summarize("hello from the meeting")

    assert constructed == {
        "api_key": "gateway-key",
        "base_url": "https://gateway.example.test/v1",
    }
    assert calls[0]["model"] == "acme/meeting-model"
    assert calls[0]["max_tokens"] == 4096
    assert summary.title == "Gateway Test"


def test_openai_compatible_summarizer_uses_placeholder_key_for_keyless_self_hosting(monkeypatch):
    constructed = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            constructed.update(kwargs)

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    OpenAICompatibleSummarizer(
        api_key="",
        model="local-model",
        base_url="http://127.0.0.1:8080/v1",
    )
    assert constructed["api_key"] == "not-needed"

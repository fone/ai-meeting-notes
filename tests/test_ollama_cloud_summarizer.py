import sys
from types import SimpleNamespace

import pytest

from meeting_notes.ai_summarizer import OllamaCloudSummarizer


def _response(content, finish_reason="stop"):
    return SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=8000),
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content=content),
            )
        ],
    )


def test_ollama_cloud_uses_reasoning_safe_output_budget(monkeypatch):
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return _response(
                """TITLE:
Infrastructure Update
OVERVIEW:
The upgrade completed.
KEY POINTS:
- vSphere is compliant
ACTION ITEMS:
None identified
DECISIONS:
- Use the current image
PARTICIPANTS:
Adam
"""
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    summary = OllamaCloudSummarizer(api_key="test-key").summarize("meeting text")

    assert calls[0]["max_tokens"] == 8192
    assert summary.title == "Infrastructure Update"
    assert summary.overview == "The upgrade completed."


def test_ollama_cloud_rejects_empty_visible_content(monkeypatch):
    class FakeCompletions:
        def create(self, **kwargs):
            return _response(None, finish_reason="length")

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setattr("meeting_notes.ai_summarizer.time.sleep", lambda _: None)

    with pytest.raises(RuntimeError, match=r"no visible summary content.*finish_reason=length"):
        OllamaCloudSummarizer(api_key="test-key").summarize("meeting text")
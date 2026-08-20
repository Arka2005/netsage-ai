"""Ollama adapter tests — fully offline. urlopen is stubbed, so these never touch a real
daemon and stay reproducible in CI [NFR-02]. The real-model smoke test is manual, not here.
"""

import io
import json
import urllib.error

import pytest

from netsage.ai import ollama as ollama_module
from netsage.ai.ollama import BackendUnreachable, OllamaClient


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _stub_urlopen(monkeypatch, body: dict, capture: dict | None = None):
    def fake_urlopen(request, timeout=None):
        if capture is not None:
            capture["url"] = request.full_url
            capture["payload"] = json.loads(request.data.decode("utf-8"))
            capture["timeout"] = timeout
        return _FakeResponse(json.dumps(body).encode("utf-8"))

    monkeypatch.setattr(ollama_module.urllib.request, "urlopen", fake_urlopen)


def test_complete_returns_message_content(monkeypatch):
    _stub_urlopen(
        monkeypatch,
        {
            "model": "gemma3:4b",
            "message": {"role": "assistant", "content": '{"case_id": "NS-021"}'},
            "prompt_eval_count": 812,
            "eval_count": 194,
        },
    )
    response = OllamaClient(model="gemma3:4b").complete("sys", "usr", temperature=0.0)

    assert response.text == '{"case_id": "NS-021"}'
    assert response.backend == "ollama"
    assert response.model == "gemma3:4b"
    assert response.prompt_tokens == 812
    assert response.completion_tokens == 194
    assert response.latency_ms >= 0


def test_request_uses_documented_parameters(monkeypatch):
    capture: dict = {}
    _stub_urlopen(monkeypatch, {"message": {"content": "{}"}}, capture)
    OllamaClient(model="gemma3:4b").complete("sys", "usr", temperature=0.0)

    assert capture["url"] == "http://localhost:11434/api/chat"
    payload = capture["payload"]
    assert payload["stream"] is False
    assert payload["format"] == "json"
    assert payload["options"]["temperature"] == 0.0
    assert payload["options"]["top_p"] == 1.0
    assert payload["options"]["num_predict"] == 1200
    assert capture["timeout"] == 120
    assert payload["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]


def test_temperature_is_passed_through(monkeypatch):
    capture: dict = {}
    _stub_urlopen(monkeypatch, {"message": {"content": "{}"}}, capture)
    OllamaClient().complete("sys", "usr", temperature=0.7)
    assert capture["payload"]["options"]["temperature"] == 0.7


def test_connection_refused_raises_backend_unreachable(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(ollama_module.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(BackendUnreachable) as excinfo:
        OllamaClient().complete("sys", "usr")
    assert "ollama serve" in str(excinfo.value)  # the message names the start command


def test_timeout_raises_backend_unreachable(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise TimeoutError("timed out")

    monkeypatch.setattr(ollama_module.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(BackendUnreachable):
        OllamaClient().complete("sys", "usr")


def test_http_error_names_the_model(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            url="http://localhost:11434/api/chat",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"model not found"}'),
        )

    monkeypatch.setattr(ollama_module.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(BackendUnreachable) as excinfo:
        OllamaClient(model="never-pulled:70b").complete("sys", "usr")
    assert "never-pulled:70b" in str(excinfo.value)
    assert "404" in str(excinfo.value)


def test_missing_message_content_yields_empty_text(monkeypatch):
    # A malformed daemon response shouldn't crash the adapter — downstream schema validation
    # turns empty text into a parse_failed, which is the documented path.
    _stub_urlopen(monkeypatch, {"model": "gemma3:4b"})
    response = OllamaClient().complete("sys", "usr")
    assert response.text == ""

"""Local Ollama backend — the default. POST /api/chat, no streaming, JSON-mode.

Uses stdlib urllib rather than requests: this is one POST to localhost, and NFR-01 says
stdlib first. See docs/ai_diagnosis_specification.md §2.
"""

import json
import time
import urllib.error
import urllib.request

from netsage.ai.client import LLMResponse

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "llama3.1:8b"
# Local 7-8B models on CPU are slow; the spec's sampling table sets this deliberately high.
DEFAULT_TIMEOUT_S = 120
_MAX_TOKENS = 1200


class BackendUnreachable(Exception):
    """The Ollama daemon isn't reachable. The CLI maps this to exit 4 with a start command."""


class OllamaClient:
    backend = "ollama"  # read by the run recorder when complete() fails [AR-06]

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        host: str = DEFAULT_HOST,
        timeout_s: int = DEFAULT_TIMEOUT_S,
    ):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout_s = timeout_s

    def complete(self, system: str, user: str, *, temperature: float = 0.0) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",  # structural pressure toward valid JSON [AR-01]
            "options": {
                "temperature": temperature,
                "top_p": 1.0,
                "num_predict": _MAX_TOKENS,
            },
        }
        request = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        start = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # The daemon answered but rejected the request — usually an unpulled model.
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            raise BackendUnreachable(
                f"Ollama returned HTTP {exc.code} for model {self.model!r}: {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise BackendUnreachable(
                f"could not reach Ollama at {self.host} ({exc}). Is it running? Start it with: ollama serve"
            ) from exc
        latency_ms = int((time.monotonic() - start) * 1000)

        return LLMResponse(
            text=body.get("message", {}).get("content", ""),
            backend="ollama",
            model=body.get("model", self.model),
            temperature=temperature,
            latency_ms=latency_ms,
            prompt_tokens=body.get("prompt_eval_count"),
            completion_tokens=body.get("eval_count"),
        )

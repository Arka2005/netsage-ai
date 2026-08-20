"""Fixture-replay backend — no network, no key. Reads <fixtures_dir>/<case_id>.json.

Used by CI, unit tests, and as the documented on-camera fallback if a real backend stalls
during the demo. See docs/ai_diagnosis_specification.md §2 (FR-11).
"""

import re
import time
from pathlib import Path

from netsage.ai.client import LLMResponse

# The prompt layout (docs/ai_diagnosis_specification.md §3.2) always includes a "case_id: NS-021"
# line under "## CASE" — the mock backend reads the case_id back out of the prompt itself rather
# than taking it as a separate parameter, since LLMClient.complete() only takes system/user text.
_CASE_ID_IN_PROMPT = re.compile(r"case_id:\s*(\S+)")


class MockClient:
    backend = "mock"  # read by the run recorder when complete() fails [AR-06]

    def __init__(self, fixtures_dir: str = "tests/fixtures/responses", model: str = "mock"):
        self.fixtures_dir = Path(fixtures_dir)
        self.model = model

    def complete(self, system: str, user: str, *, temperature: float = 0.0) -> LLMResponse:
        # The prompt may contain several "case_id: ..." lines (one per few-shot example) — the
        # real case being diagnosed is always the last one, appended after the examples.
        matches = list(_CASE_ID_IN_PROMPT.finditer(user))
        if not matches:
            raise ValueError("mock backend could not find a 'case_id: ...' line in the prompt")
        case_id = matches[-1].group(1)

        fixture_path = self.fixtures_dir / f"{case_id}.json"
        if not fixture_path.exists():
            raise FileNotFoundError(f"no mock fixture at {fixture_path}")

        start = time.monotonic()
        text = fixture_path.read_text(encoding="utf-8")
        latency_ms = int((time.monotonic() - start) * 1000)

        return LLMResponse(
            text=text,
            backend="mock",
            model=self.model,
            temperature=temperature,
            latency_ms=latency_ms,
        )

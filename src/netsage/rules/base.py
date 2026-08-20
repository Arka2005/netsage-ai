"""Finding dataclass and small text helpers shared by the rule modules.

Each rule module exposes check(case: Case) -> list[Finding]. Rules are advisory: they read the
raw show_outputs text with plain regex, the way "twenty lines of Python" would (see
docs/demo_plan.md Beat 4) — they never override a human, and a rule engine crash on one case must
not take down the others.
"""

import re
from dataclasses import dataclass

_PROMPT_LINE = re.compile(r"(?m)^(\S+)[#>]\s*(.*)$")


@dataclass
class Finding:
    rule_id: str
    severity: str
    message: str
    evidence: str


def iter_device_blocks(show_outputs: str) -> list[tuple[str, str]]:
    """Splits show_outputs into (device, block_text) pairs, one per '<DEVICE># <cmd>' prompt line.

    A device can appear more than once (multiple commands run against it) — callers that compare
    across devices should keep the first block per device, not the last.
    """
    matches = list(_PROMPT_LINE.finditer(show_outputs))
    blocks = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(show_outputs)
        blocks.append((m.group(1), show_outputs[m.start() : end]))
    return blocks


def find_line(text: str, needle: str) -> str:
    """First line of text containing needle, for use as Finding.evidence. Falls back to text itself."""
    for line in text.splitlines():
        if needle in line:
            return line.strip()
    return text.strip()

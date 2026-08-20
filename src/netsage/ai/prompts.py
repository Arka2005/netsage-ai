"""Prompt template loading and rendering. See docs/ai_diagnosis_specification.md §3.

Front matter here is always flat scalars (prompt_version/updated/notes), so a hand-rolled
splitter is enough — pulling in a YAML library for three key: value lines isn't warranted.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from netsage.cases import Case
from netsage.rules.base import Finding

_FRONT_MATTER = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


@dataclass
class PromptFile:
    prompt_version: str
    body: str


def _parse_front_matter(text: str) -> tuple[dict, str]:
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}, text.strip()
    raw_front_matter, body = match.groups()
    front_matter = {}
    for line in raw_front_matter.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            front_matter[key.strip()] = value.strip()
    return front_matter, body.strip()


def load_prompt_file(path: str) -> PromptFile:
    front_matter, body = _parse_front_matter(Path(path).read_text(encoding="utf-8"))
    return PromptFile(prompt_version=front_matter.get("prompt_version", "unknown"), body=body)


def render_case_block(case: Case, rule_findings: list[Finding]) -> str:
    """The '## CASE ... ## TASK' block — used both for the real case and, hand-authored, by
    diagnose_prompt.md's few-shot examples, so the model sees one consistent layout throughout."""
    lines = [
        "## CASE",
        f"case_id: {case.case_id}",
        "",
        "## SYMPTOM",
        case.symptom,
        "",
        "## TOPOLOGY NOTE",
        case.topology_note,
        "",
        "## SHOW OUTPUT (this is your only evidence)",
        case.show_outputs,
        "",
        "## DETERMINISTIC RULE FINDINGS (advisory — verify against the evidence yourself)",
    ]
    if rule_findings:
        for finding in rule_findings:
            lines.append(f"- {finding.rule_id} [{finding.severity}]: {finding.message}")
            lines.append(f'  evidence: "{finding.evidence}"')
    else:
        lines.append("(none)")
    lines += ["", "## TASK", "Return the diagnosis JSON object."]
    return "\n".join(lines)


def build_prompt(case: Case, rule_findings: list[Finding], prompts_dir: str = "prompts") -> tuple[str, str, str]:
    """Returns (system, user, prompt_version) — prompt_version comes from diagnose_prompt.md's
    own front matter, since that's the file whose content actually changes across iterations."""
    system_file = load_prompt_file(f"{prompts_dir}/system_prompt.md")
    diagnose_file = load_prompt_file(f"{prompts_dir}/diagnose_prompt.md")

    case_block = render_case_block(case, rule_findings)
    user = f"{diagnose_file.body}\n\n{case_block}"

    return system_file.body, user, diagnose_file.prompt_version


def build_repair_message(previous_user: str, parser_error: str, prompts_dir: str = "prompts") -> str:
    repair_file = load_prompt_file(f"{prompts_dir}/repair_prompt.md")
    repair_text = repair_file.body.replace("{{parser_error}}", parser_error)
    return f"{previous_user}\n\n{repair_text}"

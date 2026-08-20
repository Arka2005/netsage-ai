"""Parse, validate, and evidence-ground a raw LLM diagnosis response. No LLM call happens here —
this module only turns text into a validated Diagnosis (or explains why it couldn't).
See docs/ai_diagnosis_specification.md §4-5.

Scoping decisions where the docs don't fully specify behaviour (see also CLAUDE.md):
- confidently_wrong requires ground truth (FR-05/scoring.py, a later phase) and is not computed
  here — this module only sees the response and the case, never the answer key.
- rule_conflict is narrowly defined as "the model abstained while a HIGH rule finding exists" —
  the docs don't provide a rule-id -> root-cause-tag mapping needed for a fuller contradiction
  check, so this is the one direction that's actually checkable without inventing that mapping.
- The Field rules table's "no 'I have fixed' phrasing" / "imperative mood" constraint on
  fix_steps is not enforced — it's system-prompt guidance for the model, not a well-specified,
  reliably-checkable validation rule, and the documented Flags vocabulary has no slot for it.
"""

import json
import re
from dataclasses import dataclass

from netsage.cases import Case, OSI_LAYERS, ROOT_CAUSE_TAGS
from netsage.rules.base import Finding

_REQUIRED_KEYS = {
    "case_id",
    "root_cause",
    "root_cause_tag",
    "osi_layer",
    "confidence",
    "confidence_band",
    "evidence",
    "next_command",
    "fix_steps",
    "verification_steps",
    "risk_notes",
}
# requires_human_review may be present or absent — either way its value is ignored (HR-05).
_KNOWN_KEYS = _REQUIRED_KEYS | {"requires_human_review"}
_EVIDENCE_KEYS = {"quote", "source", "why"}
_VALID_SOURCES = {"symptom", "topology_note", "show_outputs"}
_CONFIDENCE_BANDS = {"low", "medium", "high"}

_FENCE_OPEN = re.compile(r"^```[^\n]*\n")
_FENCE_CLOSE = re.compile(r"\n?```\s*$")


@dataclass
class EvidenceItem:
    quote: str
    source: str
    why: str


@dataclass
class Diagnosis:
    case_id: str
    root_cause: str
    root_cause_tag: str
    osi_layer: str
    confidence: float
    confidence_band: str
    evidence: list[EvidenceItem]
    next_command: list[str]
    fix_steps: list[str]
    verification_steps: list[str]
    risk_notes: str
    requires_human_review: bool  # always True — never read from the model's response [HR-05]


@dataclass
class DiagnosisResult:
    status: str  # "ok" | "parse_failed" | "schema_invalid"
    diagnosis: Diagnosis | None
    flags: list[str]
    errors: list[str]
    raw_response: str  # stored verbatim, before any cleanup


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = _FENCE_OPEN.sub("", text, count=1)
        text = _FENCE_CLOSE.sub("", text)
    return text.strip()


def _expected_band(confidence: float) -> str:
    if confidence < 0.4:
        return "low"
    if confidence <= 0.75:
        return "medium"
    return "high"


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _validate_schema(data: dict) -> list[str]:
    """Hard checks: required keys, types, enums, no extra keys, evidence/confidence consistency."""
    errors: list[str] = []

    extra_keys = set(data) - _KNOWN_KEYS
    if extra_keys:
        errors.append(f"unknown field(s): {sorted(extra_keys)}")

    missing_keys = _REQUIRED_KEYS - set(data)
    if missing_keys:
        errors.append(f"missing required field(s): {sorted(missing_keys)}")
        return errors  # can't check anything else meaningfully without the required fields

    if not isinstance(data["case_id"], str) or not data["case_id"]:
        errors.append("case_id must be a non-empty string")
    if not isinstance(data["root_cause"], str) or not data["root_cause"].strip():
        errors.append("root_cause must be a non-empty string")
    if not isinstance(data["root_cause_tag"], str) or not data["root_cause_tag"]:
        errors.append("root_cause_tag must be a non-empty string")
    if data["osi_layer"] not in OSI_LAYERS:
        errors.append(f"osi_layer {data['osi_layer']!r} is not one of {OSI_LAYERS}")
    if not isinstance(data["risk_notes"], str):
        errors.append("risk_notes must be a string")

    confidence = data["confidence"]
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not (0.0 <= confidence <= 1.0):
        errors.append("confidence must be a float in [0, 1]")
    elif data["confidence_band"] not in _CONFIDENCE_BANDS:
        errors.append(f"confidence_band {data['confidence_band']!r} is not one of {sorted(_CONFIDENCE_BANDS)}")
    elif data["confidence_band"] != _expected_band(confidence):
        errors.append(
            f"confidence {confidence} does not match confidence_band {data['confidence_band']!r} "
            f"(expected {_expected_band(confidence)!r})"
        )

    errors.extend(_validate_evidence(data))
    errors.extend(_validate_string_list(data.get("next_command"), "next_command", min_items=1, max_items=3))
    errors.extend(_validate_string_list(data.get("fix_steps"), "fix_steps", min_items=1, max_items=6))
    errors.extend(_validate_string_list(data.get("verification_steps"), "verification_steps", min_items=1))

    return errors


def _validate_evidence(data: dict) -> list[str]:
    evidence = data.get("evidence")
    if not isinstance(evidence, list):
        return ["evidence must be a list"]

    if not evidence:
        if data.get("root_cause_tag") != "insufficient_evidence":
            return ["evidence must not be empty unless root_cause_tag is 'insufficient_evidence'"]
        return []

    if not 1 <= len(evidence) <= 4:
        return [f"evidence must have 1-4 items, got {len(evidence)}"]

    errors = []
    for i, item in enumerate(evidence):
        if not isinstance(item, dict) or set(item) != _EVIDENCE_KEYS:
            errors.append(f"evidence[{i}] must be an object with exactly {sorted(_EVIDENCE_KEYS)}")
            continue
        if item["source"] not in _VALID_SOURCES:
            errors.append(f"evidence[{i}].source {item['source']!r} is not one of {sorted(_VALID_SOURCES)}")
        if not isinstance(item["quote"], str) or not item["quote"]:
            errors.append(f"evidence[{i}].quote must be a non-empty string")
        if not isinstance(item["why"], str) or not item["why"]:
            errors.append(f"evidence[{i}].why must be a non-empty string")
    return errors


def _validate_string_list(value, field_name: str, *, min_items: int, max_items: int | None = None) -> list[str]:
    if not isinstance(value, list):
        return [f"{field_name} must be a list"]
    if len(value) < min_items or (max_items is not None and len(value) > max_items):
        bound = f"{min_items}-{max_items}" if max_items else f"at least {min_items}"
        return [f"{field_name} must have {bound} items, got {len(value)}"]
    if not all(isinstance(v, str) and v for v in value):
        return [f"{field_name} items must all be non-empty strings"]
    return []


def _check_evidence_grounding(evidence: list[EvidenceItem], case: Case) -> bool:
    """Returns True if every quote is a verbatim (whitespace-normalised) substring of its
    declared source field. Grounding failure never invalidates the diagnosis — it's a flag."""
    context = case.to_prompt_context()
    for item in evidence:
        source_text = _normalize_whitespace(context[item.source])
        if _normalize_whitespace(item.quote) not in source_text:
            return False
    return True


def parse_diagnosis(raw_text: str, case: Case, rule_findings: list[Finding] | None = None) -> DiagnosisResult:
    rule_findings = rule_findings or []
    cleaned = _strip_markdown_fences(raw_text)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return DiagnosisResult(status="parse_failed", diagnosis=None, flags=[], errors=[f"invalid JSON: {exc}"], raw_response=raw_text)

    if not isinstance(data, dict):
        return DiagnosisResult(
            status="schema_invalid", diagnosis=None, flags=[], errors=["top-level JSON value is not an object"], raw_response=raw_text
        )

    errors = _validate_schema(data)
    if errors:
        return DiagnosisResult(status="schema_invalid", diagnosis=None, flags=[], errors=errors, raw_response=raw_text)

    evidence = [EvidenceItem(**item) for item in data["evidence"]]
    diagnosis = Diagnosis(
        case_id=data["case_id"],
        root_cause=data["root_cause"],
        root_cause_tag=data["root_cause_tag"],
        osi_layer=data["osi_layer"],
        confidence=float(data["confidence"]),
        confidence_band=data["confidence_band"],
        evidence=evidence,
        next_command=list(data["next_command"]),
        fix_steps=list(data["fix_steps"]),
        verification_steps=list(data["verification_steps"]),
        risk_notes=data["risk_notes"],
        requires_human_review=True,  # hard-coded — the model's value, if any, is never read [HR-05]
    )

    flags = []
    if not _check_evidence_grounding(evidence, case):
        flags.append("hallucinated_evidence")
    if diagnosis.root_cause_tag not in ROOT_CAUSE_TAGS:
        flags.append("unknown_tag")
    if diagnosis.root_cause_tag == "insufficient_evidence":
        flags.append("abstained")
        if any(f.severity == "HIGH" for f in rule_findings):
            flags.append("rule_conflict")

    return DiagnosisResult(status="ok", diagnosis=diagnosis, flags=flags, errors=[], raw_response=raw_text)

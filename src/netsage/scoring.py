"""Per-case sub-scores and run-level metrics. See docs/ai_diagnosis_specification.md §6 [FR-05].

This is the only module that compares a diagnosis against ground truth. ai/schema.py
deliberately never sees the answer key, which is why confidently_wrong is computed here and
not there (see CLAUDE.md, "Known scoping decisions").

Scoring a failed case: the spec doesn't say what `scores` holds when status != "ok" and no
diagnosis exists. Smallest defensible choice — the run record carries `scores: null`, and the
case still counts in `total`. It is therefore counted as not-grounded and not-abstained, so a
parse failure drags accuracy down rather than quietly vanishing from the denominator.
"""

import re
from dataclasses import dataclass

from netsage.ai.schema import Diagnosis
from netsage.cases import Case

_ABSTAIN_TAG = "insufficient_evidence"


@dataclass
class CaseScores:
    root_cause_match: bool
    osi_match: bool
    next_command_match: bool
    evidence_grounded: bool
    abstained: bool
    confidently_wrong: bool


@dataclass
class RunMetrics:
    total: int
    answered: int  # total - abstained, the accuracy denominator
    root_cause_match: int
    osi_match: int
    next_command_match: int
    evidence_grounded: int
    abstained: int
    parse_failed: int
    schema_invalid: int
    backend_error: int
    confidently_wrong: int
    confidently_wrong_cases: list[str]
    root_cause_accuracy: float | None
    osi_accuracy: float | None
    grounding_rate: float
    abstain_rate: float


def _osi_tokens(layer: str) -> set[str]:
    """'L3/L4' -> {'L3', 'L4'}. Compound layers are intentional in the dataset, and the spec
    scores them by set overlap: L3/L4 vs L4 matches, L2 vs L7 does not."""
    return {token.strip().upper() for token in layer.split("/") if token.strip()}


def _normalize_command(command: str) -> str:
    """Lowercase, collapse whitespace, and strip a trailing '| ...' filter segment.

    Only the trailing pipe filter is stripped — the dataset also contains host-side commands
    like 'ipconfig /all on PC5' that must survive normalisation untouched.
    """
    without_filter = command.split("|", 1)[0]
    return re.sub(r"\s+", " ", without_filter).strip().lower()


def score_case(diagnosis: Diagnosis, case: Case, flags: list[str]) -> CaseScores:
    """Scores one validated diagnosis against the case's ground truth."""
    truth = case.ground_truth()

    root_cause_match = diagnosis.root_cause_tag == truth["expected_root_cause"]
    osi_match = bool(_osi_tokens(diagnosis.osi_layer) & _osi_tokens(truth["osi_layer"]))

    expected_command = _normalize_command(truth["expected_next_command"])
    proposed_commands = {_normalize_command(c) for c in diagnosis.next_command}
    next_command_match = expected_command in proposed_commands

    # Grounding was already verified in ai/schema.py against the case text; reuse its verdict
    # rather than re-implementing the substring check here.
    evidence_grounded = "hallucinated_evidence" not in flags

    abstained = diagnosis.root_cause_tag == _ABSTAIN_TAG
    confidently_wrong = diagnosis.confidence_band == "high" and not root_cause_match

    return CaseScores(
        root_cause_match=root_cause_match,
        osi_match=osi_match,
        next_command_match=next_command_match,
        evidence_grounded=evidence_grounded,
        abstained=abstained,
        confidently_wrong=confidently_wrong,
    )


def aggregate(records: list[dict]) -> RunMetrics:
    """Run-level metrics from a list of run records (the JSONL lines of one run)."""
    total = len(records)
    counts = dict.fromkeys(
        ["root_cause_match", "osi_match", "next_command_match", "evidence_grounded", "abstained", "confidently_wrong"], 0
    )
    status_counts = {"parse_failed": 0, "schema_invalid": 0, "backend_error": 0}
    confidently_wrong_cases: list[str] = []

    for record in records:
        status_counts[record["status"]] = status_counts.get(record["status"], 0) + 1
        scores = record.get("scores")
        if not scores:
            continue  # non-ok case: counts in total, contributes no matches
        for key in counts:
            if scores.get(key):
                counts[key] += 1
        if scores.get("confidently_wrong"):
            confidently_wrong_cases.append(record["case_id"])

    abstained = counts["abstained"]
    answered = total - abstained

    return RunMetrics(
        total=total,
        answered=answered,
        root_cause_match=counts["root_cause_match"],
        osi_match=counts["osi_match"],
        next_command_match=counts["next_command_match"],
        evidence_grounded=counts["evidence_grounded"],
        abstained=abstained,
        parse_failed=status_counts.get("parse_failed", 0),
        schema_invalid=status_counts.get("schema_invalid", 0),
        backend_error=status_counts.get("backend_error", 0),
        confidently_wrong=counts["confidently_wrong"],
        confidently_wrong_cases=confidently_wrong_cases,
        # Abstentions are excluded from the accuracy denominator and reported separately —
        # otherwise a model that refuses to answer looks identical to one that is wrong.
        root_cause_accuracy=(counts["root_cause_match"] / answered) if answered else None,
        osi_accuracy=(counts["osi_match"] / answered) if answered else None,
        grounding_rate=(counts["evidence_grounded"] / total) if total else 0.0,
        abstain_rate=(abstained / total) if total else 0.0,
    )

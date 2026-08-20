"""The human review gate. Walks a run's pending cases, shows the reviewer everything HR-02
requires side by side, and records a verdict. See functional_specification.md §2.4.

The system never applies a fix or claims a case resolved — it only records what a human decided
[HR-05]. input_fn/output_fn are injected so the flow is testable without a terminal.
"""

import json
import pathlib
from typing import Callable

from netsage.cases import ROOT_CAUSE_TAGS, Case
from netsage.review.store import (
    ACCEPTED,
    EDITED,
    FAILURE_MODES,
    REJECTED,
    Review,
    ReviewValidationError,
    append_review,
    latest_verdicts,
    load_reviews,
    utc_now,
)

_RULE = "─" * 68


def load_run_records(runs_dir: str, run_id: str) -> list[dict]:
    path = pathlib.Path(runs_dir) / f"{run_id}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"no run artifact at {path}")
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def render_case(record: dict, case: Case) -> str:
    """The per-case review screen. Shows AI diagnosis, rule findings and ground truth side by
    side [HR-02]. Internal plumbing (raw_response, prompt_version, latency) is deliberately
    omitted — the reviewer is judging the diagnosis, not the pipeline."""
    lines = [
        _RULE,
        f"{case.case_id}  {case.title}        {case.category} · {case.severity} · {case.difficulty}",
        _RULE,
        "SYMPTOM",
        f"  {case.symptom}",
        "",
        "SHOW OUTPUT (evidence)",
    ]
    lines += [f"  {line}" for line in case.show_outputs.splitlines()]
    lines.append("")

    lines.append("RULE FINDINGS")
    if record.get("rule_findings"):
        for finding in record["rule_findings"]:
            lines.append(f"  {finding['rule_id']}  {finding['severity']}  {finding['message']}")
    else:
        lines.append("  (none)")
    lines.append("")

    truth = case.ground_truth()
    diagnosis = record.get("diagnosis")
    scores = record.get("scores") or {}

    if diagnosis is None:
        lines += [
            f"AI DIAGNOSIS: none — status {record.get('status')}",
            f"  errors: {'; '.join(record.get('errors') or []) or '(none recorded)'}",
            "",
            "GROUND TRUTH",
            f"  root cause : {truth['expected_root_cause']}",
            f"  osi layer  : {truth['osi_layer']}",
            f"  next cmd   : {truth['expected_next_command']}",
        ]
    else:
        def mark(key: str) -> str:
            return "✔" if scores.get(key) else "✘"

        grounded = "✔" if scores.get("evidence_grounded") else "✘ NOT GROUNDED"
        lines += [
            "AI DIAGNOSIS                                        GROUND TRUTH",
            f"  root cause : {diagnosis['root_cause_tag']:<28} {mark('root_cause_match')}   {truth['expected_root_cause']}",
            f"  osi layer  : {diagnosis['osi_layer']:<28} {mark('osi_match')}   {truth['osi_layer']}",
            f"  confidence : {diagnosis['confidence']} ({diagnosis['confidence_band']})"
            + ("            ← confidently wrong" if scores.get("confidently_wrong") else ""),
            f"  evidence   : {len(diagnosis['evidence'])} quote(s)                    {grounded}",
            f"  next cmd   : {(diagnosis['next_command'] or [''])[0]:<28} {mark('next_command_match')}   {truth['expected_next_command']}",
            "",
            "  explanation: " + diagnosis["root_cause"],
            "",
            "  evidence quotes:",
        ]
        for item in diagnosis["evidence"]:
            lines.append(f'    - "{item["quote"]}"')
            lines.append(f"      why: {item['why']}")
        if not diagnosis["evidence"]:
            lines.append("    (none — the model abstained)")
        lines.append("")
        lines.append("  fix_steps:")
        for i, step in enumerate(diagnosis["fix_steps"], start=1):
            lines.append(f"    {i}. {step}")
        lines.append("")
        lines.append(f"  ground truth fix: {truth['expected_fix_steps']}")

    if record.get("flags"):
        lines += ["", f"VALIDATION FLAGS: {', '.join(record['flags'])}"]

    return "\n".join(lines)


def _ask(input_fn, output_fn, prompt: str) -> str:
    output_fn(prompt)
    try:
        return input_fn()
    except EOFError:
        return "q"


def _ask_required(input_fn, output_fn, prompt: str, error: str) -> str | None:
    """Re-prompts until non-empty. Returns None if the reviewer aborts with EOF."""
    while True:
        value = _ask(input_fn, output_fn, prompt).strip()
        if value:
            return value
        output_fn(f"  ! {error}")


def _ask_failure_mode(input_fn, output_fn) -> str | None:
    output_fn("  failure mode:")
    for i, mode in enumerate(FAILURE_MODES, start=1):
        output_fn(f"    {i}. {mode}")
    while True:
        choice = _ask(input_fn, output_fn, "  failure mode (number or name) > ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(FAILURE_MODES):
            return FAILURE_MODES[int(choice) - 1]
        if choice in FAILURE_MODES:
            return choice
        output_fn("  ! not a valid failure mode")


def _ask_corrected_tag(input_fn, output_fn) -> str:
    """Blank is allowed (the reviewer may correct only the fix). A non-blank value must be a
    real tag — an invented tag here would silently corrupt per-category dashboard analysis."""
    while True:
        value = _ask(input_fn, output_fn, "  corrected root cause tag (blank to skip) > ").strip()
        if not value or value in ROOT_CAUSE_TAGS:
            return value
        output_fn(f"  ! {value!r} is not in the root-cause tag vocabulary")


def review_run(
    run_id: str,
    records: list[dict],
    cases_by_id: dict[str, Case],
    reviews_path: str,
    reviewer: str,
    input_fn: Callable[[], str] = input,
    output_fn: Callable[[str], None] = print,
) -> dict:
    """Walks pending cases and records verdicts. Returns a summary dict.

    Resumable: cases that already carry a verdict for this run are skipped, so re-running
    picks up at the first Pending case.
    """
    already_reviewed = latest_verdicts(load_reviews(reviews_path), run_id)
    pending = [r for r in records if r["case_id"] not in already_reviewed]

    summary = {"reviewed": 0, "skipped": 0, "quit": False, "already_reviewed": len(already_reviewed)}

    if not pending:
        output_fn(f"All {len(records)} case(s) in {run_id} already have a verdict — nothing pending.")
        return summary

    output_fn(f"{len(pending)} case(s) pending review in {run_id} (reviewer: {reviewer})")

    for record in pending:
        case = cases_by_id.get(record["case_id"])
        if case is None:
            output_fn(f"[WARN] {record['case_id']} is in the run but not in the dataset — skipping")
            summary["skipped"] += 1
            continue

        output_fn("")
        output_fn(render_case(record, case))
        output_fn("")
        choice = _ask(input_fn, output_fn, "[A]ccept   [E]dit   [R]eject   [S]kip   [Q]uit\n> ").strip().lower()

        if choice in ("q", "quit"):
            summary["quit"] = True
            output_fn("Quitting — cases without a verdict remain Pending.")
            break
        if choice in ("s", "skip", ""):
            summary["skipped"] += 1
            output_fn(f"{record['case_id']} left Pending.")
            continue

        verdict = {"a": ACCEPTED, "e": EDITED, "r": REJECTED}.get(choice[:1])
        if verdict is None:
            summary["skipped"] += 1
            output_fn(f"  ! unrecognised choice {choice!r} — {record['case_id']} left Pending.")
            continue

        review = Review(
            run_id=run_id,
            case_id=record["case_id"],
            verdict=verdict,
            reviewer=reviewer,
            reviewed_at_utc=utc_now(),
        )

        if verdict == EDITED:
            review.corrected_root_cause = _ask_corrected_tag(input_fn, output_fn)
            review.corrected_fix = _ask(input_fn, output_fn, "  corrected fix (blank to skip) > ").strip()
            if not (review.corrected_root_cause or review.corrected_fix):
                output_fn("  ! an Edit needs at least one correction — leaving Pending.")
                summary["skipped"] += 1
                continue
            review.reason = _ask_required(input_fn, output_fn, "  reason (required) > ", "a reason is required [HR-03]")
        elif verdict == REJECTED:
            review.failure_mode = _ask_failure_mode(input_fn, output_fn)
            review.corrected_root_cause = _ask_corrected_tag(input_fn, output_fn)
            review.reason = _ask_required(input_fn, output_fn, "  reason (required) > ", "a reason is required [HR-03]")

        try:
            append_review(reviews_path, review)
        except ReviewValidationError as exc:
            output_fn(f"  ! {exc} — {record['case_id']} left Pending.")
            summary["skipped"] += 1
            continue

        summary["reviewed"] += 1
        output_fn(f"  {record['case_id']} recorded as {verdict}.")

    return summary

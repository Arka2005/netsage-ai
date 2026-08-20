"""Entry point: netsage validate | check | run | review | dashboard."""

import argparse
import dataclasses
import datetime
import json
import pathlib
import sys

from netsage import rules
from netsage.ai.client import LLMResponse
from netsage.ai.mock import MockClient
from netsage.ai.schema import Diagnosis, parse_diagnosis
from netsage.cases import CATEGORIES, REQUIRED_FIELDS, SEVERITIES, SchemaError, load_cases, validate_cases

# Placeholder prompt content — Phase 6 replaces both of these with the real, versioned
# prompts/system_prompt.md and prompts/diagnose_prompt.md (front-matter, few-shot examples).
# The layout ("## CASE" / "case_id: ...") already matches docs/ai_diagnosis_specification.md
# sec3.2 so ai/mock.py can find the case_id, and so Phase 6 is a drop-in replacement, not a rewrite
# of the pipeline around it.
_PROMPT_VERSION = "v0-dev"
_SYSTEM_PROMPT_PLACEHOLDER = (
    "You are a senior network engineer reviewing a junior's Packet Tracer lab. Output one JSON "
    "object matching the diagnosis schema and nothing else — no prose, no markdown fences."
)


def _build_user_message(case, rule_findings: list) -> str:
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


def _make_backend(name: str, model: str | None, fixtures_dir: str):
    if name == "mock":
        return MockClient(fixtures_dir=fixtures_dir, model=model or "mock")
    raise NotImplementedError(f"--backend {name!r} isn't implemented yet — use --backend mock")


def _make_run_id(backend: str, model: str, prompt_version: str) -> str:
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%MZ")
    return f"{timestamp}-{backend}-{model}-{prompt_version}"


def _diagnosis_to_dict(diagnosis: Diagnosis | None) -> dict | None:
    if diagnosis is None:
        return None
    data = dataclasses.asdict(diagnosis)
    return data


def _diagnose_case(case, backend, rule_findings: list, temperature: float) -> dict:
    """Calls the backend, parses/validates the response, and does the one bounded repair retry
    on malformed JSON [AR-08]. Always returns a complete run-record dict, never raises."""
    system = _SYSTEM_PROMPT_PLACEHOLDER
    user = _build_user_message(case, rule_findings)
    rule_findings_dicts = [dataclasses.asdict(f) for f in rule_findings]

    try:
        response: LLMResponse = backend.complete(system, user, temperature=temperature)
    except Exception as exc:
        return {
            "case_id": case.case_id,
            "backend": getattr(backend, "backend", "unknown"),
            "model": getattr(backend, "model", "unknown"),
            "temperature": temperature,
            "prompt_version": _PROMPT_VERSION,
            "rule_findings": rule_findings_dicts,
            "raw_response": "",
            "diagnosis": None,
            "status": "backend_error",
            "flags": [],
            "scores": None,  # filled in by scoring.py, once ground truth comparison exists
            "latency_ms": 0,
            "review": None,  # always null in this file — joined against artifacts/reviews.csv at read time
            "errors": [str(exc)],
        }

    result = parse_diagnosis(response.text, case, rule_findings)

    if result.status == "parse_failed":
        # One bounded repair retry, then give up — never a silent loop. [AR-08]
        repair_user = (
            f"{user}\n\n## REPAIR\nYour previous response was not valid JSON. Parser error: "
            f"{result.errors[0] if result.errors else 'unknown error'}. "
            "Return ONLY the corrected JSON object, nothing else."
        )
        try:
            response = backend.complete(system, repair_user, temperature=temperature)
            result = parse_diagnosis(response.text, case, rule_findings)
        except Exception:
            pass  # keep the original parse_failed result — the retry attempt itself errored

    return {
        "case_id": case.case_id,
        "backend": response.backend,
        "model": response.model,
        "temperature": response.temperature,
        "prompt_version": _PROMPT_VERSION,
        "rule_findings": rule_findings_dicts,
        "raw_response": result.raw_response,  # verbatim, before any cleanup
        "diagnosis": _diagnosis_to_dict(result.diagnosis),
        "status": result.status,
        "flags": result.flags,
        "scores": None,  # filled in by scoring.py, once ground truth comparison exists
        "latency_ms": response.latency_ms,
        "review": None,  # always null in this file — joined against artifacts/reviews.csv at read time
        "errors": result.errors,
    }


def _load_cases_or_report(path: str) -> tuple[list, int]:
    """Returns (cases, 0) on success, or (None, exit_code) on a load failure the caller should return."""
    try:
        return load_cases(path), 0
    except FileNotFoundError:
        print(f"[ERROR] cases.csv not found at {path}")
        return None, 2
    except (OSError, UnicodeDecodeError) as exc:
        # A directory path (PermissionError/IsADirectoryError, both OSError subclasses) or a
        # non-UTF-8 CSV (UnicodeDecodeError, not an OSError) — both are "unreadable", exit 2's
        # documented meaning (functional_specification.md sec2.1), not an uncaught traceback.
        print(f"[ERROR] cases.csv is unreadable at {path}: {exc}")
        return None, 2
    except SchemaError as exc:
        print(f"[ERROR] schema violation: {exc}")
        return None, 1


def _cmd_validate(args: argparse.Namespace) -> int:
    cases, exit_code = _load_cases_or_report(args.path)
    if cases is None:
        return exit_code

    report = validate_cases(cases)

    if report.errors:
        print(f"[ERROR] {len(report.errors)} schema violation(s):")
        for error in report.errors:
            print(f"  - {error}")
        return 1

    print(f"✔ {report.case_count} cases loaded from {args.path}")
    print(f"✔ schema OK — {len(REQUIRED_FIELDS)}/{len(REQUIRED_FIELDS)} columns")
    print("✔ case_id unique")

    coverage = " · ".join(f"{cat} {report.category_counts.get(cat, 0)}" for cat in CATEGORIES)
    print(f"✔ coverage: {coverage}")

    severity_line = " · ".join(f"{sev} {report.severity_counts.get(sev, 0)}" for sev in SEVERITIES)
    print(f"✔ severity: {severity_line}")

    for warning in report.warnings:
        print(f"⚠ {warning}")

    return 0


def _print_findings(case, findings: list) -> None:
    print(f"{case.case_id}  {case.title}   [{case.category} · {case.severity}]")
    print()
    for finding in findings:
        print(f"  {finding.rule_id:<24}{finding.severity:<8}{finding.message}")
        print(f'      evidence: "{finding.evidence}"')
    print()
    print(f"{len(findings)} findings · 0 errors")


def _cmd_check(args: argparse.Namespace) -> int:
    cases, exit_code = _load_cases_or_report(args.dataset)
    if cases is None:
        # netsage check's exit codes are documented as 0/1/3 (functional_specification.md
        # sec2.2), where 1 specifically means "case not found" — but _load_cases_or_report
        # returns 1 for a schema violation, which would collide with that meaning here. This
        # isn't resolved by the spec (it never defines a dataset-load-failure code for check at
        # all), so as the smallest defensible choice: fold any dataset-load failure (missing
        # file, unreadable file, or bad schema) into exit 2 for check, keeping 1 reserved
        # strictly for "case not found". See CLAUDE.md's "Known scoping decisions" section.
        return 2 if exit_code == 1 else exit_code

    if args.case:
        case = next((c for c in cases if c.case_id == args.case), None)
        if case is None:
            print(f"[ERROR] case {args.case!r} not found in {args.dataset}")
            return 1
        try:
            findings = rules.check(case)
        except Exception as exc:
            print(f"[ERROR] rule engine crashed on {case.case_id}: {exc}")
            return 3
        _print_findings(case, findings)
        return 0

    if args.all:
        hit_counts = {rule_id: 0 for rule_id in rules.ALL_RULE_IDS}
        error_count = 0
        for case in cases:
            try:
                findings = rules.check(case)
            except Exception as exc:
                print(f"[ERROR] rule engine crashed on {case.case_id}: {exc}")
                error_count += 1
                continue
            for finding in findings:
                hit_counts[finding.rule_id] = hit_counts.get(finding.rule_id, 0) + 1

        print(f"Rule hit table across {len(cases)} cases:")
        for rule_id in rules.ALL_RULE_IDS:
            print(f"  {rule_id:<28}{hit_counts[rule_id]}")
        print()
        print(f"{len(cases)} cases checked · {error_count} rule engine error(s)")
        return 3 if error_count else 0

    print("[ERROR] specify --case NS-021 or --all")
    return 1


def _cmd_run(args: argparse.Namespace) -> int:
    cases, exit_code = _load_cases_or_report(args.dataset)
    if cases is None:
        return 2 if exit_code == 1 else exit_code  # same remap reasoning as _cmd_check

    if args.case:
        selected = [c for c in cases if c.case_id == args.case]
        if not selected:
            print(f"[ERROR] case {args.case!r} not found in {args.dataset}")
            return 1
    elif args.all:
        selected = cases
    else:
        print("[ERROR] specify --case NS-021 or --all")
        return 1

    try:
        backend = _make_backend(args.backend, args.model, args.fixtures_dir)
    except NotImplementedError as exc:
        print(f"[ERROR] {exc}")
        return 4  # "backend unreachable" per functional_specification.md sec4's error table

    run_id = args.run_id or _make_run_id(args.backend, args.model or "mock", _PROMPT_VERSION)
    run_path = pathlib.Path(args.runs_dir) / f"{run_id}.jsonl"
    run_path.parent.mkdir(parents=True, exist_ok=True)

    ok_count = 0
    with open(run_path, "a", encoding="utf-8") as run_file:
        for case in selected:
            try:
                rule_findings = rules.check(case)
                rules_degraded = False
            except Exception as exc:
                print(f"[ERROR] rule engine crashed on {case.case_id}: {exc} — continuing with no rule findings")
                rule_findings = []
                rules_degraded = True

            record = _diagnose_case(case, backend, rule_findings, args.temperature)
            record["run_id"] = run_id
            record["timestamp_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            record["rules_degraded"] = rules_degraded
            run_file.write(json.dumps(record) + "\n")

            status_mark = "✔" if record["status"] == "ok" else "✘"
            print(f"{case.case_id}  {case.title}")
            print(f"  status        : {record['status']} {status_mark}")
            if record["diagnosis"]:
                print(f"  root cause tag: {record['diagnosis']['root_cause_tag']}")
                print(f"  confidence    : {record['diagnosis']['confidence']} ({record['diagnosis']['confidence_band']})")
            if record["flags"]:
                print(f"  flags         : {', '.join(record['flags'])}")
            print("  verdict       : PENDING HUMAN REVIEW")
            print()

            if record["status"] == "ok":
                ok_count += 1

    print(f"run {run_id}   {len(selected)} case(s)")
    print(f"  ok            {ok_count}/{len(selected)}")
    print(f"all {len(selected)} case(s) are PENDING human review → run: netsage review --run {run_id}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="netsage")
    subparsers = parser.add_subparsers(dest="command")

    validate_parser = subparsers.add_parser("validate", help="Schema-check data/cases.csv")
    validate_parser.add_argument("--path", default="data/cases.csv")
    validate_parser.set_defaults(func=_cmd_validate)

    check_parser = subparsers.add_parser("check", help="Run deterministic rules only, no LLM")
    check_parser.add_argument("--case")
    check_parser.add_argument("--all", action="store_true")
    check_parser.add_argument("--dataset", default="data/cases.csv")
    check_parser.set_defaults(func=_cmd_check)

    run_parser = subparsers.add_parser("run", help="Run the AI diagnosis pipeline")
    run_parser.add_argument("--backend", choices=["mock", "ollama", "api"], default="mock")
    run_parser.add_argument("--model", default=None)
    run_parser.add_argument("--case")
    run_parser.add_argument("--all", action="store_true")
    run_parser.add_argument("--dataset", default="data/cases.csv")
    run_parser.add_argument("--temperature", type=float, default=0.0)
    run_parser.add_argument("--run-id", default=None)
    run_parser.add_argument("--runs-dir", default="artifacts/runs")
    run_parser.add_argument("--fixtures-dir", default="tests/fixtures/responses")
    run_parser.set_defaults(func=_cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252, which can't print ✔/·/⚠
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

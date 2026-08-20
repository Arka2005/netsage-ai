"""Entry point: netsage validate | check | run | review | dashboard."""

import argparse
import dataclasses
import datetime
import json
import pathlib
import re
import sys

from netsage import rules
from netsage.ai.client import LLMResponse
from netsage.ai.mock import MockClient
from netsage.ai.ollama import DEFAULT_HOST as OLLAMA_DEFAULT_HOST
from netsage.ai.ollama import DEFAULT_MODEL as OLLAMA_DEFAULT_MODEL
from netsage.ai.ollama import DEFAULT_TIMEOUT_S as OLLAMA_DEFAULT_TIMEOUT_S
from netsage.ai.ollama import BackendUnreachable, OllamaClient
from netsage.ai.prompts import build_prompt, build_repair_message, load_prompt_file
from netsage.ai.schema import Diagnosis, parse_diagnosis
from netsage.cases import CATEGORIES, REQUIRED_FIELDS, SEVERITIES, SchemaError, load_cases, validate_cases
from netsage.scoring import aggregate, score_case


def _make_backend(
    name: str,
    model: str | None,
    fixtures_dir: str,
    ollama_host: str = OLLAMA_DEFAULT_HOST,
    timeout_s: int = OLLAMA_DEFAULT_TIMEOUT_S,
):
    if name == "mock":
        return MockClient(fixtures_dir=fixtures_dir, model=model or "mock")
    if name == "ollama":
        return OllamaClient(model=model or OLLAMA_DEFAULT_MODEL, host=ollama_host, timeout_s=timeout_s)
    raise NotImplementedError(f"--backend {name!r} isn't implemented yet — use --backend mock or --backend ollama")


_UNSAFE_RUN_ID_CHARS = re.compile(r'[:\\/*?"<>|\s]+')


def _make_run_id(backend: str, model: str, prompt_version: str) -> str:
    """run_id doubles as a filename, so the model name has to be filesystem-safe.

    Ollama model names always contain a colon ("gemma3:4b", "llama3.1:8b"). On Windows a colon
    in a path opens an NTFS alternate data stream instead of erroring, so the JSONL silently
    lands in a hidden stream and the visible artifact is 0 bytes — the audit trail is lost with
    no warning [FR-07]. Sanitising to a hyphen also matches the documented example run_id in
    system_architecture.md §5 ("...-ollama-llama3.1-8b-v1.2").
    """
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%MZ")
    safe_model = _UNSAFE_RUN_ID_CHARS.sub("-", model)
    return f"{timestamp}-{backend}-{safe_model}-{prompt_version}"


def _diagnosis_to_dict(diagnosis: Diagnosis | None) -> dict | None:
    if diagnosis is None:
        return None
    data = dataclasses.asdict(diagnosis)
    return data


def _diagnose_case(case, backend, rule_findings: list, temperature: float, prompts_dir: str) -> dict:
    """Calls the backend, parses/validates the response, and does the one bounded repair retry
    on malformed JSON [AR-08]. Always returns a complete run-record dict, never raises."""
    system, user, prompt_version = build_prompt(case, rule_findings, prompts_dir)
    rule_findings_dicts = [dataclasses.asdict(f) for f in rule_findings]

    try:
        response: LLMResponse = backend.complete(system, user, temperature=temperature)
    except BackendUnreachable:
        # The daemon itself is down/unreachable — that's a whole-run failure, not a per-case
        # one. Let it propagate so _cmd_run can abort with the documented exit 4 instead of
        # grinding out 36 identical backend_error records. [functional_specification.md §4]
        raise
    except Exception as exc:
        return {
            "case_id": case.case_id,
            "backend": getattr(backend, "backend", "unknown"),
            "model": getattr(backend, "model", "unknown"),
            "temperature": temperature,
            "prompt_version": prompt_version,
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
        repair_user = build_repair_message(
            user, result.errors[0] if result.errors else "unknown error", prompts_dir
        )
        try:
            response = backend.complete(system, repair_user, temperature=temperature)
            result = parse_diagnosis(response.text, case, rule_findings)
        except Exception:
            pass  # keep the original parse_failed result — the retry attempt itself errored

    # Scored only when a validated diagnosis exists; non-ok cases carry scores: null and are
    # counted as neither grounded nor abstained by scoring.aggregate(). [FR-05]
    scores = (
        dataclasses.asdict(score_case(result.diagnosis, case, result.flags))
        if result.diagnosis is not None
        else None
    )

    return {
        "case_id": case.case_id,
        "backend": response.backend,
        "model": response.model,
        "temperature": response.temperature,
        "prompt_version": prompt_version,
        "rule_findings": rule_findings_dicts,
        "raw_response": result.raw_response,  # verbatim, before any cleanup
        "diagnosis": _diagnosis_to_dict(result.diagnosis),
        "status": result.status,
        "flags": result.flags,
        "scores": scores,
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


def _print_run_summary(run_id: str, records: list[dict]) -> None:
    """The documented run summary (functional_specification.md §2.3).

    Note on denominators: ai_diagnosis_specification.md §6 defines root-cause and OSI accuracy
    over (total - abstained), so those two lines show the answered count as the denominator.
    Grounding, abstain and parse-failure lines are over the full total. The §2.3 sample output
    prints "28/36 (77.8%)" for root cause, which is X/total rather than the §6 formula — the
    formula is authoritative here, so the denominators are shown explicitly to avoid ambiguity.
    """
    metrics = aggregate(records)

    def pct(value: float | None) -> str:
        return "  n/a " if value is None else f"{value * 100:5.1f}%"

    print(f"run {run_id}   {metrics.total} case(s)")
    print(f"  root cause match   {metrics.root_cause_match}/{metrics.answered}  ({pct(metrics.root_cause_accuracy)})")
    print(f"  osi layer match    {metrics.osi_match}/{metrics.answered}  ({pct(metrics.osi_accuracy)})")
    print(f"  next command match {metrics.next_command_match}/{metrics.answered}")
    print(f"  evidence grounded  {metrics.evidence_grounded}/{metrics.total}  ({pct(metrics.grounding_rate)})")
    print(f"  abstained          {metrics.abstained}/{metrics.total}")
    print(f"  parse failures     {metrics.parse_failed}/{metrics.total}")
    if metrics.schema_invalid or metrics.backend_error:
        print(f"  schema invalid     {metrics.schema_invalid}/{metrics.total}")
        print(f"  backend errors     {metrics.backend_error}/{metrics.total}")
    suffix = "      ← review these first" if metrics.confidently_wrong else ""
    print(f"  confidently wrong  {metrics.confidently_wrong}{suffix}")
    if metrics.confidently_wrong_cases:
        print(f"      {', '.join(metrics.confidently_wrong_cases)}")


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
        backend = _make_backend(args.backend, args.model, args.fixtures_dir, args.ollama_host, args.timeout)
    except NotImplementedError as exc:
        print(f"[ERROR] {exc}")
        return 4  # "backend unreachable" per functional_specification.md sec4's error table

    prompt_version = load_prompt_file(f"{args.prompts_dir}/diagnose_prompt.md").prompt_version
    run_id = args.run_id or _make_run_id(args.backend, args.model or "mock", prompt_version)
    run_path = pathlib.Path(args.runs_dir) / f"{run_id}.jsonl"
    run_path.parent.mkdir(parents=True, exist_ok=True)

    ok_count = 0
    records: list[dict] = []
    with open(run_path, "a", encoding="utf-8") as run_file:
        for case in selected:
            try:
                rule_findings = rules.check(case)
                rules_degraded = False
            except Exception as exc:
                print(f"[ERROR] rule engine crashed on {case.case_id}: {exc} — continuing with no rule findings")
                rule_findings = []
                rules_degraded = True

            try:
                record = _diagnose_case(case, backend, rule_findings, args.temperature, args.prompts_dir)
            except BackendUnreachable as exc:
                print(f"[ERROR] {exc}")
                print(f"[ERROR] aborting run after {ok_count} completed case(s) — no further cases attempted.")
                print("        Use --backend mock to run offline against recorded fixtures.")
                return 4

            record["run_id"] = run_id
            record["timestamp_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            record["rules_degraded"] = rules_degraded
            run_file.write(json.dumps(record) + "\n")
            run_file.flush()  # a long ollama run should leave a usable artifact if interrupted
            records.append(record)

            status_mark = "✔" if record["status"] == "ok" else "✘"
            print(f"{case.case_id}  {case.title}")
            print(f"  status        : {record['status']} {status_mark}")
            if record["diagnosis"]:
                expected = case.ground_truth()["expected_root_cause"]
                scores = record["scores"] or {}
                tag_mark = "✔" if scores.get("root_cause_match") else "✘"
                osi_mark = "✔" if scores.get("osi_match") else "✘"
                print(f"  root cause tag: {record['diagnosis']['root_cause_tag']:<32}[expected: {expected}] {tag_mark}")
                print(f"  osi layer     : {record['diagnosis']['osi_layer']:<32}[expected: {case.osi_layer}] {osi_mark}")
                print(f"  confidence    : {record['diagnosis']['confidence']} ({record['diagnosis']['confidence_band']})")
            if record["flags"]:
                print(f"  flags         : {', '.join(record['flags'])}")
            print(f"  latency       : {record['latency_ms']} ms")
            print("  verdict       : PENDING HUMAN REVIEW")
            print()

            if record["status"] == "ok":
                ok_count += 1

    _print_run_summary(run_id, records)
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
    run_parser.add_argument("--prompts-dir", default="prompts")
    run_parser.add_argument("--ollama-host", default=OLLAMA_DEFAULT_HOST)
    run_parser.add_argument(
        "--timeout",
        type=int,
        default=OLLAMA_DEFAULT_TIMEOUT_S,
        help="per-case backend timeout in seconds (raise it for slow hardware or large models)",
    )
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

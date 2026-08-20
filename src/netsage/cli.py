"""Entry point: netsage validate | check | run | review | dashboard."""

import argparse
import sys

from netsage import rules
from netsage.cases import CATEGORIES, REQUIRED_FIELDS, SEVERITIES, SchemaError, load_cases, validate_cases


def _load_cases_or_report(path: str) -> tuple[list, int]:
    """Returns (cases, 0) on success, or (None, exit_code) on a load failure the caller should return."""
    try:
        return load_cases(path), 0
    except FileNotFoundError:
        print(f"[ERROR] cases.csv not found at {path}")
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
        return exit_code

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

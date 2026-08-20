"""Entry point: netsage validate | check | run | review | dashboard."""

import argparse
import sys

from netsage.cases import CATEGORIES, REQUIRED_FIELDS, SEVERITIES, SchemaError, load_cases, validate_cases


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        cases = load_cases(args.path)
    except FileNotFoundError:
        print(f"[ERROR] cases.csv not found at {args.path}")
        return 2
    except SchemaError as exc:
        print(f"[ERROR] schema violation: {exc}")
        return 1

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="netsage")
    subparsers = parser.add_subparsers(dest="command")

    validate_parser = subparsers.add_parser("validate", help="Schema-check data/cases.csv")
    validate_parser.add_argument("--path", default="data/cases.csv")
    validate_parser.set_defaults(func=_cmd_validate)

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

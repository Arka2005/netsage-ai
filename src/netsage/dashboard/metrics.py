"""Aggregates runs + reviews + the dataset into the seven documented dashboard panels.

See functional_specification.md §2.5. Pure data assembly — rendering lives in render.py.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from netsage.cases import BRIEF_MANDATED_CATEGORIES, CATEGORIES, DIFFICULTIES, SEVERITIES, Case
from netsage.review.store import Review, agreement, latest_verdicts
from netsage.scoring import aggregate

_MIN_CASES_PER_FAMILY = 3


@dataclass
class GroupAccuracy:
    name: str
    total: int
    root_cause_match: int
    osi_match: int
    next_command_match: int

    @property
    def root_cause_pct(self) -> float | None:
        return (self.root_cause_match / self.total * 100) if self.total else None


@dataclass
class CaseRow:
    """One row of the CSV export / per-case dashboard table."""

    case_id: str
    title: str
    category: str
    severity: str
    difficulty: str
    status: str
    ai_tag: str
    expected_tag: str
    root_cause_match: bool
    osi_match: bool
    next_command_match: bool
    evidence_grounded: bool
    confidence: str
    confidence_band: str
    confidently_wrong: bool
    flags: str
    verdict: str  # "Pending" until a human issues one [HR-01]
    reviewer: str


@dataclass
class DashboardData:
    run_id: str
    # panel 1 — dataset composition
    category_counts: dict[str, int]
    severity_counts: dict[str, int]
    # panel 2 — accuracy
    overall: object  # scoring.RunMetrics
    by_category: list[GroupAccuracy]
    # panel 3 — agreement
    agreement: object  # review.store.AgreementMetrics
    # panel 4 — evidence quality
    hallucinated_cases: list[str]
    # panel 5 — calibration
    by_band: list[GroupAccuracy]
    confidently_wrong_cases: list[str]
    # panel 6 — difficulty
    by_difficulty: list[GroupAccuracy]
    # panel 7 — coverage gaps
    thin_categories: list[str]
    pending_cases: list[str]
    # per-case detail, backing the CSV export
    rows: list[CaseRow] = field(default_factory=list)


def _group_accuracy(name: str, records: list[dict]) -> GroupAccuracy:
    def count(key: str) -> int:
        return sum(1 for r in records if (r.get("scores") or {}).get(key))

    return GroupAccuracy(
        name=name,
        total=len(records),
        root_cause_match=count("root_cause_match"),
        osi_match=count("osi_match"),
        next_command_match=count("next_command_match"),
    )


def build(run_id: str, cases: list[Case], records: list[dict], reviews: list[Review]) -> DashboardData:
    cases_by_id = {case.case_id: case for case in cases}
    verdicts = latest_verdicts(reviews, run_id)

    by_category: dict[str, list[dict]] = defaultdict(list)
    by_difficulty: dict[str, list[dict]] = defaultdict(list)
    by_band: dict[str, list[dict]] = defaultdict(list)
    hallucinated_cases: list[str] = []
    pending_cases: list[str] = []
    rows: list[CaseRow] = []

    for record in records:
        case = cases_by_id.get(record["case_id"])
        if case is None:
            continue  # a run referencing a case no longer in the dataset — excluded, not guessed
        diagnosis = record.get("diagnosis") or {}
        scores = record.get("scores") or {}
        flags = record.get("flags") or []

        by_category[case.category].append(record)
        by_difficulty[case.difficulty].append(record)
        band = diagnosis.get("confidence_band") or "(no diagnosis)"
        by_band[band].append(record)

        if "hallucinated_evidence" in flags:
            hallucinated_cases.append(case.case_id)

        review = verdicts.get(case.case_id)
        if review is None:
            pending_cases.append(case.case_id)

        rows.append(
            CaseRow(
                case_id=case.case_id,
                title=case.title,
                category=case.category,
                severity=case.severity,
                difficulty=case.difficulty,
                status=record.get("status", ""),
                ai_tag=diagnosis.get("root_cause_tag", ""),
                expected_tag=case.expected_root_cause,
                root_cause_match=bool(scores.get("root_cause_match")),
                osi_match=bool(scores.get("osi_match")),
                next_command_match=bool(scores.get("next_command_match")),
                evidence_grounded=bool(scores.get("evidence_grounded")),
                confidence=str(diagnosis.get("confidence", "")),
                confidence_band=diagnosis.get("confidence_band", ""),
                confidently_wrong=bool(scores.get("confidently_wrong")),
                flags=", ".join(flags),
                verdict=review.verdict if review else "Pending",
                reviewer=review.reviewer if review else "",
            )
        )

    overall = aggregate(records)
    dataset_categories = Counter(case.category for case in cases)

    return DashboardData(
        run_id=run_id,
        category_counts={c: dataset_categories.get(c, 0) for c in CATEGORIES if dataset_categories.get(c)},
        severity_counts={s: sum(1 for c in cases if c.severity == s) for s in SEVERITIES},
        overall=overall,
        by_category=[_group_accuracy(c, by_category[c]) for c in CATEGORIES if c in by_category],
        agreement=agreement(reviews, run_id, total_cases=len(records)),
        hallucinated_cases=hallucinated_cases,
        by_band=[_group_accuracy(b, by_band[b]) for b in ("high", "medium", "low", "(no diagnosis)") if b in by_band],
        confidently_wrong_cases=overall.confidently_wrong_cases,
        by_difficulty=[_group_accuracy(d, by_difficulty[d]) for d in DIFFICULTIES if d in by_difficulty],
        thin_categories=[
            c for c in BRIEF_MANDATED_CATEGORIES if dataset_categories.get(c, 0) < _MIN_CASES_PER_FAMILY
        ],
        pending_cases=pending_cases,
        rows=rows,
    )

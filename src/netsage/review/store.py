"""Append-only review store (artifacts/reviews.csv) and the agreement metric.

Schema is the nine columns documented in functional_specification.md §2.4. Nothing here is
invented; the one implementation-only convention is documented on latest_verdicts().
"""

import csv
import datetime
import pathlib
from dataclasses import asdict, dataclass

# Exact column order from functional_specification.md §2.4.
REVIEW_COLUMNS = [
    "run_id",
    "case_id",
    "verdict",
    "reviewer",
    "reviewed_at_utc",
    "failure_mode",
    "corrected_root_cause",
    "corrected_fix",
    "reason",
]

ACCEPTED = "Accepted"
EDITED = "Edited"
REJECTED = "Rejected"
VERDICTS = (ACCEPTED, EDITED, REJECTED)

# functional_specification.md §2.6.
FAILURE_MODES = (
    "wrong_layer",
    "plausible_but_unsupported",
    "hallucinated_evidence",
    "overconfident",
    "incomplete_fix",
    "unsafe_recommendation",
    "missed_security_implication",
    "should_have_abstained",
)


class ReviewValidationError(Exception):
    """A verdict that violates the rules of the gate (HR-03) — e.g. an empty reason."""


@dataclass
class Review:
    run_id: str
    case_id: str
    verdict: str
    reviewer: str
    reviewed_at_utc: str
    failure_mode: str = ""
    corrected_root_cause: str = ""
    corrected_fix: str = ""
    reason: str = ""


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_review(review: Review) -> None:
    """Enforces the rules of the gate. Raises ReviewValidationError on violation.

    - Edited and Rejected both require a non-empty reason [HR-03].
    - Rejected additionally requires a failure-mode category from the documented vocabulary.
    - Edited requires at least one correction (root cause and/or fix), per §2.4's
      "supplies the corrected root cause and/or fix".
    - Corrections on Rejected are optional (§2.6's log example carries one).
    """
    if review.verdict not in VERDICTS:
        raise ReviewValidationError(f"verdict must be one of {list(VERDICTS)}, got {review.verdict!r}")
    if not review.reviewer.strip():
        raise ReviewValidationError("reviewer identity is required [HR-04]")

    if review.verdict in (EDITED, REJECTED) and not review.reason.strip():
        raise ReviewValidationError(f"{review.verdict} requires a non-empty reason [HR-03]")

    if review.verdict == REJECTED and review.failure_mode not in FAILURE_MODES:
        raise ReviewValidationError(
            f"Rejected requires a failure mode from {list(FAILURE_MODES)}, got {review.failure_mode!r}"
        )

    if review.verdict == EDITED and not (review.corrected_root_cause.strip() or review.corrected_fix.strip()):
        raise ReviewValidationError("Edited requires a corrected root cause and/or a corrected fix")

    if review.failure_mode and review.failure_mode not in FAILURE_MODES:
        raise ReviewValidationError(f"unknown failure mode {review.failure_mode!r}")


def append_review(path: str, review: Review) -> None:
    """Appends one validated row, writing the header if the file is new. Append-only —
    an existing row is never rewritten or deleted."""
    validate_review(review)
    file_path = pathlib.Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not file_path.exists() or file_path.stat().st_size == 0

    with open(file_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS, quoting=csv.QUOTE_ALL, lineterminator="\n")
        if is_new:
            writer.writeheader()
        writer.writerow(asdict(review))


def load_reviews(path: str) -> list[Review]:
    """Every row, in file order. Returns [] when the file doesn't exist yet."""
    file_path = pathlib.Path(path)
    if not file_path.exists():
        return []
    with open(file_path, newline="", encoding="utf-8") as f:
        return [Review(**{col: row.get(col, "") or "" for col in REVIEW_COLUMNS}) for row in csv.DictReader(f)]


def latest_verdicts(reviews: list[Review], run_id: str) -> dict[str, Review]:
    """Current verdict per case for one run.

    Implementation-only convention: the store is append-only and the session is resumable, so a
    case can legitimately appear more than once (a reviewer re-reviewing it). The spec doesn't
    say which wins; the last row for a case is treated as current, and earlier rows are retained
    as history. See CLAUDE.md, "Known scoping decisions".
    """
    current: dict[str, Review] = {}
    for review in reviews:
        if review.run_id == run_id:
            current[review.case_id] = review
    return current


@dataclass
class AgreementMetrics:
    accepted: int
    edited: int
    rejected: int
    reviewed: int  # the denominator: accepted + edited + rejected
    pending: int
    agreement: float | None  # None when nothing has been reviewed yet


def agreement(reviews: list[Review], run_id: str, total_cases: int) -> AgreementMetrics:
    """agreement = Accepted / (Accepted + Edited + Rejected) — functional_specification.md §2.5.

    Pending cases are deliberately excluded from the denominator and reported separately, so an
    unreviewed run can never inflate the score. With nothing reviewed the denominator is zero and
    agreement is None (not 0.0, which would read as "0% agreement" rather than "no data yet").
    """
    current = latest_verdicts(reviews, run_id)
    counts = {verdict: 0 for verdict in VERDICTS}
    for review in current.values():
        if review.verdict in counts:
            counts[review.verdict] += 1

    reviewed = sum(counts.values())
    return AgreementMetrics(
        accepted=counts[ACCEPTED],
        edited=counts[EDITED],
        rejected=counts[REJECTED],
        reviewed=reviewed,
        pending=max(total_cases - reviewed, 0),
        agreement=(counts[ACCEPTED] / reviewed) if reviewed else None,
    )

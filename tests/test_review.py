"""Human review gate tests. Input is scripted, so no terminal is required."""

import json

import pytest

from netsage.cases import Case
from netsage.review.cli import render_case, review_run
from netsage.review.store import (
    ACCEPTED,
    EDITED,
    REJECTED,
    Review,
    ReviewValidationError,
    agreement,
    append_review,
    latest_verdicts,
    load_reviews,
    utc_now,
    validate_review,
)


def _case(case_id="NS-021"):
    return Case(
        case_id=case_id,
        title="ACL applied in the wrong direction",
        category="ACL",
        concept_tag="acl-direction",
        symptom="Guest traffic reaches the servers.",
        topology_note="ACL 110 on R1 Gi0/0.99.",
        show_outputs="R1# show access-lists 110\n 10 deny ip any any (0 matches)",
        expected_fault="ACL on the wrong side.",
        expected_root_cause="acl_wrong_direction",
        osi_layer="L3/L4",
        severity="High",
        expected_next_command="show ip interface Gi0/0.99 | include access list",
        expected_fix_steps="Move the ACL to Gi0/0.30.",
        source_lab="lab-acl.pkt",
        difficulty="Medium",
    )


def _record(case_id="NS-021", tag="acl_wrong_direction", root_cause_match=True, status="ok"):
    return {
        "case_id": case_id,
        "status": status,
        "flags": [],
        "errors": [],
        "rule_findings": [
            {"rule_id": "R11_acl_zero_match", "severity": "HIGH", "message": "0 matches", "evidence": "e"}
        ],
        "diagnosis": {
            "case_id": case_id,
            "root_cause": "The ACL is bound on the wrong subinterface.",
            "root_cause_tag": tag,
            "osi_layer": "L3/L4",
            "confidence": 0.82,
            "confidence_band": "high",
            "evidence": [{"quote": "10 deny ip any any (0 matches)", "source": "show_outputs", "why": "never matches"}],
            "next_command": ["show ip interface Gi0/0.99 | include access list"],
            "fix_steps": ["Remove it from Gi0/0.99", "Apply on Gi0/0.30"],
            "verification_steps": ["Re-test"],
            "risk_notes": "none",
            "requires_human_review": True,
        },
        "scores": {
            "root_cause_match": root_cause_match,
            "osi_match": True,
            "next_command_match": True,
            "evidence_grounded": True,
            "abstained": False,
            "confidently_wrong": not root_cause_match,
        },
    }


def _scripted(answers):
    """An input_fn that replays a list of answers, then raises EOFError (reviewer walked away)."""
    queue = list(answers)

    def _input() -> str:
        if not queue:
            raise EOFError
        return queue.pop(0)

    return _input


def _silent(_message):
    pass


def _run(answers, records=None, reviews_path="", reviewer="tester", cases=None):
    records = records if records is not None else [_record()]
    cases_by_id = cases if cases is not None else {"NS-021": _case()}
    return review_run(
        "RUN-1", records, cases_by_id, reviews_path, reviewer, input_fn=_scripted(answers), output_fn=_silent
    )


# --- validation (HR-03) -----------------------------------------------------


def test_accept_needs_no_reason():
    validate_review(Review("R", "NS-021", ACCEPTED, "alice", utc_now()))


def test_edited_requires_a_reason():
    review = Review("R", "NS-021", EDITED, "alice", utc_now(), corrected_root_cause="acl_rule_order", reason="")
    with pytest.raises(ReviewValidationError, match="reason"):
        validate_review(review)


def test_rejected_requires_a_reason():
    review = Review("R", "NS-021", REJECTED, "alice", utc_now(), failure_mode="wrong_layer", reason="   ")
    with pytest.raises(ReviewValidationError, match="reason"):
        validate_review(review)


def test_rejected_requires_a_known_failure_mode():
    review = Review("R", "NS-021", REJECTED, "alice", utc_now(), failure_mode="", reason="wrong")
    with pytest.raises(ReviewValidationError, match="failure mode"):
        validate_review(review)

    review.failure_mode = "not_a_real_mode"
    with pytest.raises(ReviewValidationError, match="failure mode"):
        validate_review(review)


def test_edited_requires_at_least_one_correction():
    review = Review("R", "NS-021", EDITED, "alice", utc_now(), reason="needs work")
    with pytest.raises(ReviewValidationError, match="corrected"):
        validate_review(review)


def test_reviewer_identity_is_required():
    with pytest.raises(ReviewValidationError, match="reviewer"):
        validate_review(Review("R", "NS-021", ACCEPTED, "  ", utc_now()))


def test_unknown_verdict_is_rejected():
    with pytest.raises(ReviewValidationError, match="verdict"):
        validate_review(Review("R", "NS-021", "Maybe", "alice", utc_now()))


# --- store round-trip -------------------------------------------------------


def test_append_and_load_round_trip(tmp_path):
    path = str(tmp_path / "reviews.csv")
    append_review(path, Review("RUN-1", "NS-021", ACCEPTED, "alice", utc_now()))
    append_review(
        path,
        Review("RUN-1", "NS-022", REJECTED, "bob", utc_now(), failure_mode="overconfident", reason="pattern-matched"),
    )

    reviews = load_reviews(path)
    assert [r.case_id for r in reviews] == ["NS-021", "NS-022"]
    assert reviews[1].verdict == REJECTED
    assert reviews[1].failure_mode == "overconfident"
    assert reviews[1].reason == "pattern-matched"


def test_load_reviews_on_missing_file_is_empty(tmp_path):
    assert load_reviews(str(tmp_path / "nope.csv")) == []


def test_append_writes_the_documented_header(tmp_path):
    path = tmp_path / "reviews.csv"
    append_review(str(path), Review("RUN-1", "NS-021", ACCEPTED, "alice", utc_now()))
    header = path.read_text(encoding="utf-8").splitlines()[0]
    assert header == (
        '"run_id","case_id","verdict","reviewer","reviewed_at_utc","failure_mode",'
        '"corrected_root_cause","corrected_fix","reason"'
    )


def test_latest_verdict_wins_and_history_is_kept(tmp_path):
    path = str(tmp_path / "reviews.csv")
    append_review(path, Review("RUN-1", "NS-021", ACCEPTED, "alice", utc_now()))
    append_review(path, Review("RUN-1", "NS-021", REJECTED, "bob", utc_now(), failure_mode="wrong_layer", reason="no"))

    reviews = load_reviews(path)
    assert len(reviews) == 2  # append-only: nothing overwritten
    assert latest_verdicts(reviews, "RUN-1")["NS-021"].verdict == REJECTED


def test_reviews_are_scoped_to_their_run(tmp_path):
    path = str(tmp_path / "reviews.csv")
    append_review(path, Review("RUN-1", "NS-021", ACCEPTED, "alice", utc_now()))
    append_review(path, Review("RUN-2", "NS-021", REJECTED, "bob", utc_now(), failure_mode="wrong_layer", reason="x"))

    reviews = load_reviews(path)
    assert latest_verdicts(reviews, "RUN-1")["NS-021"].verdict == ACCEPTED
    assert latest_verdicts(reviews, "RUN-2")["NS-021"].verdict == REJECTED


# --- agreement (§2.5) -------------------------------------------------------


def test_agreement_is_accepted_over_all_verdicts():
    reviews = [
        Review("R", "NS-001", ACCEPTED, "a", "t"),
        Review("R", "NS-002", ACCEPTED, "a", "t"),
        Review("R", "NS-003", EDITED, "a", "t", corrected_root_cause="x", reason="r"),
        Review("R", "NS-004", REJECTED, "a", "t", failure_mode="wrong_layer", reason="r"),
    ]
    metrics = agreement(reviews, "R", total_cases=10)

    assert (metrics.accepted, metrics.edited, metrics.rejected) == (2, 1, 1)
    assert metrics.reviewed == 4
    assert metrics.agreement == 0.5
    assert metrics.pending == 6  # excluded from the denominator, reported separately


def test_agreement_is_none_when_nothing_reviewed():
    metrics = agreement([], "R", total_cases=36)
    assert metrics.reviewed == 0
    assert metrics.agreement is None  # not 0.0 — "no data yet", not "0% agreement"
    assert metrics.pending == 36


def test_agreement_counts_a_re_reviewed_case_once():
    reviews = [
        Review("R", "NS-001", ACCEPTED, "a", "t"),
        Review("R", "NS-001", REJECTED, "b", "t", failure_mode="wrong_layer", reason="r"),
    ]
    metrics = agreement(reviews, "R", total_cases=1)
    assert metrics.reviewed == 1
    assert metrics.rejected == 1
    assert metrics.accepted == 0


# --- the interactive flow ---------------------------------------------------


def test_accept_records_a_verdict(tmp_path):
    path = str(tmp_path / "reviews.csv")
    summary = _run(["a"], reviews_path=path)

    assert summary["reviewed"] == 1
    review = load_reviews(path)[0]
    assert review.verdict == ACCEPTED
    assert review.case_id == "NS-021"
    assert review.run_id == "RUN-1"
    assert review.reviewer == "tester"
    assert review.reviewed_at_utc.endswith("Z")  # UTC stamp [HR-04]


def test_edit_persists_the_corrected_diagnosis(tmp_path):
    path = str(tmp_path / "reviews.csv")
    summary = _run(["e", "acl_rule_order", "Reorder the deny below the permit", "tag was close but not exact"], reviews_path=path)

    assert summary["reviewed"] == 1
    review = load_reviews(path)[0]
    assert review.verdict == EDITED
    assert review.corrected_root_cause == "acl_rule_order"
    assert review.corrected_fix == "Reorder the deny below the permit"
    assert review.reason == "tag was close but not exact"


def test_reject_persists_failure_mode_and_reason(tmp_path):
    path = str(tmp_path / "reviews.csv")
    summary = _run(["r", "2", "acl_blocks_return_traffic", "pattern-matched a familiar ACL case"], reviews_path=path)

    assert summary["reviewed"] == 1
    review = load_reviews(path)[0]
    assert review.verdict == REJECTED
    assert review.failure_mode == "plausible_but_unsupported"  # option 2 in the vocabulary
    assert review.corrected_root_cause == "acl_blocks_return_traffic"
    assert review.reason == "pattern-matched a familiar ACL case"


def test_reject_accepts_a_failure_mode_by_name(tmp_path):
    path = str(tmp_path / "reviews.csv")
    _run(["r", "overconfident", "", "0.98 on a wrong answer"], reviews_path=path)
    assert load_reviews(path)[0].failure_mode == "overconfident"


def test_empty_reason_is_re_prompted_until_supplied(tmp_path):
    path = str(tmp_path / "reviews.csv")
    # blank, whitespace, then a real reason
    _run(["r", "wrong_layer", "", "", "   ", "diagnosed L4 when the interface was down"], reviews_path=path)
    assert load_reviews(path)[0].reason == "diagnosed L4 when the interface was down"


def test_invalid_corrected_tag_is_re_prompted(tmp_path):
    path = str(tmp_path / "reviews.csv")
    _run(["e", "not_a_real_tag", "acl_rule_order", "", "close enough to edit"], reviews_path=path)
    assert load_reviews(path)[0].corrected_root_cause == "acl_rule_order"


def test_edit_with_no_corrections_leaves_the_case_pending(tmp_path):
    path = str(tmp_path / "reviews.csv")
    summary = _run(["e", "", ""], reviews_path=path)

    assert summary["reviewed"] == 0
    assert summary["skipped"] == 1
    assert load_reviews(path) == []  # nothing written [HR-01: stays Pending]


def test_skip_leaves_the_case_pending(tmp_path):
    path = str(tmp_path / "reviews.csv")
    summary = _run(["s"], reviews_path=path)

    assert summary["reviewed"] == 0
    assert summary["skipped"] == 1
    assert load_reviews(path) == []


def test_unrecognised_choice_leaves_the_case_pending(tmp_path):
    path = str(tmp_path / "reviews.csv")
    summary = _run(["zzz"], reviews_path=path)
    assert summary["reviewed"] == 0
    assert load_reviews(path) == []


def test_quit_stops_the_session_without_reviewing_the_rest(tmp_path):
    path = str(tmp_path / "reviews.csv")
    records = [_record("NS-021"), _record("NS-022")]
    cases = {"NS-021": _case("NS-021"), "NS-022": _case("NS-022")}
    summary = _run(["a", "q"], records=records, reviews_path=path, cases=cases)

    assert summary["reviewed"] == 1
    assert summary["quit"] is True
    assert [r.case_id for r in load_reviews(path)] == ["NS-021"]


def test_session_is_resumable_and_skips_already_reviewed_cases(tmp_path):
    path = str(tmp_path / "reviews.csv")
    records = [_record("NS-021"), _record("NS-022")]
    cases = {"NS-021": _case("NS-021"), "NS-022": _case("NS-022")}

    _run(["a", "q"], records=records, reviews_path=path, cases=cases)
    summary = _run(["a"], records=records, reviews_path=path, cases=cases)

    assert summary["already_reviewed"] == 1
    assert summary["reviewed"] == 1
    assert sorted(r.case_id for r in load_reviews(path)) == ["NS-021", "NS-022"]


def test_nothing_pending_is_reported_and_writes_nothing(tmp_path):
    path = str(tmp_path / "reviews.csv")
    _run(["a"], reviews_path=path)
    summary = _run([], reviews_path=path)
    assert summary["reviewed"] == 0
    assert len(load_reviews(path)) == 1


# --- the review screen (HR-02, HR-05) ---------------------------------------


def test_screen_shows_diagnosis_rule_findings_and_ground_truth_together():
    screen = render_case(_record(), _case())

    assert "SYMPTOM" in screen
    assert "SHOW OUTPUT (evidence)" in screen
    assert "R11_acl_zero_match" in screen  # rule findings
    assert "AI DIAGNOSIS" in screen and "GROUND TRUTH" in screen
    assert "acl_wrong_direction" in screen
    assert "0.82 (high)" in screen
    assert "show ip interface Gi0/0.99" in screen  # next command
    assert "Remove it from Gi0/0.99" in screen  # fix steps
    assert "10 deny ip any any (0 matches)" in screen  # evidence quote


def test_screen_calls_out_a_confidently_wrong_case():
    screen = render_case(_record(tag="acl_blocks_dns", root_cause_match=False), _case())
    assert "confidently wrong" in screen
    assert "acl_blocks_dns" in screen
    assert "acl_wrong_direction" in screen  # the ground truth is still shown alongside


def test_screen_hides_pipeline_internals_from_the_reviewer():
    record = _record()
    record["raw_response"] = "SHOULD-NOT-APPEAR"
    record["prompt_version"] = "v1.1"
    record["latency_ms"] = 12345
    screen = render_case(record, _case())

    assert "SHOULD-NOT-APPEAR" not in screen
    assert "12345" not in screen


def test_screen_handles_a_case_with_no_diagnosis():
    record = _record(status="schema_invalid")
    record["diagnosis"] = None
    record["scores"] = None
    record["errors"] = ["missing required field(s): ['root_cause']"]
    screen = render_case(record, _case())

    assert "AI DIAGNOSIS: none" in screen
    assert "schema_invalid" in screen
    assert "acl_wrong_direction" in screen  # ground truth still shown so a verdict is possible


def test_a_case_missing_from_the_dataset_is_skipped_not_crashed(tmp_path):
    path = str(tmp_path / "reviews.csv")
    summary = _run(["a"], records=[_record("NS-999")], reviews_path=path, cases={})
    assert summary["skipped"] == 1
    assert load_reviews(path) == []


# --- regressions from the Phase 5-10 code review ----------------------------


def test_eof_at_failure_mode_prompt_aborts_instead_of_looping(tmp_path):
    """Regression: EOF was mapped to the literal "q", which is neither a digit nor a valid
    failure mode, so the prompt re-asked forever (reproduced at >2000 iterations)."""
    path = str(tmp_path / "reviews.csv")
    summary = _run(["r"], reviews_path=path)  # queue empties at the failure-mode prompt

    assert summary["quit"] is True
    assert summary["reviewed"] == 0
    assert load_reviews(path) == []  # nothing partial written — the case stays Pending


def test_eof_at_corrected_tag_prompt_aborts_instead_of_looping(tmp_path):
    path = str(tmp_path / "reviews.csv")
    summary = _run(["e"], reviews_path=path)

    assert summary["quit"] is True
    assert load_reviews(path) == []


def test_eof_at_reason_prompt_does_not_record_a_placeholder_reason(tmp_path):
    """Regression: EOF returned "q", which passed the non-empty check and was stored as the
    mandatory reason — a meaningless audit record that fed straight into the AI log."""
    path = str(tmp_path / "reviews.csv")
    summary = _run(["r", "overconfident", ""], reviews_path=path)  # EOF at the reason prompt

    assert summary["quit"] is True
    assert load_reviews(path) == []


def test_typed_q_still_quits_normally(tmp_path):
    # The sentinel change must not break the documented [Q]uit key.
    path = str(tmp_path / "reviews.csv")
    summary = _run(["q"], reviews_path=path)
    assert summary["quit"] is True
    assert load_reviews(path) == []


def test_corrupt_run_artifact_raises_a_clear_error(tmp_path):
    from netsage.review.cli import load_run_records

    (tmp_path / "X.jsonl").write_text('{"case_id": "NS-001"}\n{truncated', encoding="utf-8")
    with pytest.raises(ValueError, match="line 2 is not valid JSON"):
        load_run_records(str(tmp_path), "X")

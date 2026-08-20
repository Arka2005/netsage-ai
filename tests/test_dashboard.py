"""Dashboard aggregation, rendering and Responsible AI log tests."""

from netsage.cases import Case
from netsage.dashboard import metrics as dashboard_metrics
from netsage.dashboard import render as dashboard_render
from netsage.review.store import ACCEPTED, EDITED, REJECTED, Review


def _case(case_id, category="ACL", difficulty="Medium", severity="High", tag="acl_wrong_direction"):
    return Case(
        case_id=case_id,
        title=f"title {case_id}",
        category=category,
        concept_tag="c",
        symptom="s",
        topology_note="t",
        show_outputs="R1# show access-lists 110",
        expected_fault="f",
        expected_root_cause=tag,
        osi_layer="L3/L4",
        severity=severity,
        expected_next_command="show access-lists 110",
        expected_fix_steps="fix",
        source_lab="lab.pkt",
        difficulty=difficulty,
    )


def _record(case_id, *, tag="acl_wrong_direction", match=True, band="high", status="ok", flags=None):
    diagnosis = None if status != "ok" else {
        "root_cause_tag": tag,
        "osi_layer": "L3/L4",
        "confidence": 0.82,
        "confidence_band": band,
        "evidence": [],
        "next_command": ["show access-lists 110"],
        "fix_steps": ["f"],
        "root_cause": "r",
    }
    scores = None if status != "ok" else {
        "root_cause_match": match,
        "osi_match": True,
        "next_command_match": True,
        "evidence_grounded": "hallucinated_evidence" not in (flags or []),
        "abstained": False,
        "confidently_wrong": band == "high" and not match,
    }
    return {
        "case_id": case_id,
        "status": status,
        "flags": flags or [],
        "errors": [],
        "rule_findings": [],
        "diagnosis": diagnosis,
        "scores": scores,
    }


def _build(cases=None, records=None, reviews=None, run_id="RUN-1"):
    cases = cases or [_case("NS-021")]
    records = records if records is not None else [_record("NS-021")]
    return dashboard_metrics.build(run_id, cases, records, reviews or [])


# --- aggregation ------------------------------------------------------------


def test_dataset_composition_counts_categories_and_severities():
    cases = [_case("NS-001", category="VLAN"), _case("NS-002", category="VLAN"), _case("NS-003", category="ACL")]
    data = _build(cases=cases, records=[_record("NS-001")])
    assert data.category_counts["VLAN"] == 2
    assert data.category_counts["ACL"] == 1
    assert data.severity_counts["High"] == 3


def test_per_category_accuracy_splits_correctly():
    cases = [_case("NS-001", category="VLAN"), _case("NS-002", category="ACL")]
    records = [_record("NS-001", match=True), _record("NS-002", match=False)]
    data = _build(cases=cases, records=records)

    by_name = {g.name: g for g in data.by_category}
    assert by_name["VLAN"].root_cause_match == 1
    assert by_name["ACL"].root_cause_match == 0


def test_difficulty_split():
    cases = [_case("NS-001", difficulty="Easy"), _case("NS-002", difficulty="Hard")]
    records = [_record("NS-001", match=True), _record("NS-002", match=False)]
    data = _build(cases=cases, records=records)

    by_name = {g.name: g for g in data.by_difficulty}
    assert by_name["Easy"].root_cause_match == 1
    assert by_name["Hard"].root_cause_match == 0


def test_calibration_groups_by_confidence_band():
    cases = [_case("NS-001"), _case("NS-002")]
    records = [_record("NS-001", band="high"), _record("NS-002", band="low")]
    data = _build(cases=cases, records=records)
    assert {g.name for g in data.by_band} == {"high", "low"}


def test_hallucinated_cases_are_listed():
    data = _build(records=[_record("NS-021", flags=["hallucinated_evidence"])])
    assert data.hallucinated_cases == ["NS-021"]


def test_confidently_wrong_cases_are_listed():
    data = _build(records=[_record("NS-021", match=False, band="high")])
    assert data.confidently_wrong_cases == ["NS-021"]


def test_pending_cases_are_listed_when_unreviewed():
    data = _build()
    assert data.pending_cases == ["NS-021"]
    assert data.agreement.agreement is None


def test_reviewed_cases_are_not_pending():
    reviews = [Review("RUN-1", "NS-021", ACCEPTED, "alice", "t")]
    data = _build(reviews=reviews)
    assert data.pending_cases == []
    assert data.agreement.agreement == 1.0
    assert data.rows[0].verdict == ACCEPTED
    assert data.rows[0].reviewer == "alice"


def test_thin_categories_are_flagged():
    data = _build(cases=[_case("NS-021", category="ACL")])
    assert "VLAN" in data.thin_categories  # brief-mandated but absent from this dataset


def test_a_record_for_an_unknown_case_is_excluded_not_guessed():
    data = _build(cases=[_case("NS-021")], records=[_record("NS-021"), _record("NS-999")])
    assert [row.case_id for row in data.rows] == ["NS-021"]


def test_failed_case_row_has_empty_diagnosis_fields():
    data = _build(records=[_record("NS-021", status="schema_invalid")])
    row = data.rows[0]
    assert row.status == "schema_invalid"
    assert row.ai_tag == ""
    assert row.root_cause_match is False


# --- HTML rendering ---------------------------------------------------------


def test_html_is_self_contained_and_has_all_seven_panels():
    html = dashboard_render.render_html(_build())

    assert html.startswith("<!doctype html>")
    # no external resources — the file must open anywhere with no network [FR-08]
    assert "http://" not in html and "https://" not in html
    assert "<script" not in html
    for heading in [
        "1 · Dataset composition",
        "2 · Accuracy",
        "3 · AI-vs-human agreement",
        "4 · Evidence quality",
        "5 · Calibration",
        "6 · Difficulty",
        "7 · Coverage gaps",
    ]:
        assert heading in html


def test_html_shows_the_agreement_formula_and_excludes_pending():
    html = dashboard_render.render_html(_build())
    assert "Accepted / (Accepted + Edited + Rejected)" in html
    assert "Pending (excluded from the denominator)" in html


def test_html_calls_out_confidently_wrong_in_red():
    html = dashboard_render.render_html(_build(records=[_record("NS-021", match=False, band="high")]))
    assert "danger" in html
    assert "confidently wrong" in html


def test_html_escapes_model_supplied_content():
    # root_cause_tag comes from the model, so it is untrusted text reaching the report.
    records = [_record("NS-021", tag="<script>alert(1)</script>", match=False)]
    html = dashboard_render.render_html(_build(records=records))

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# --- CSV export -------------------------------------------------------------


def test_csv_export_has_a_row_per_case():
    csv_text = dashboard_render.render_csv(_build())
    lines = csv_text.strip().splitlines()
    assert len(lines) == 2  # header + 1 case
    assert '"case_id"' in lines[0]
    assert "NS-021" in lines[1]


def test_csv_export_is_safe_when_there_are_no_rows():
    data = _build(records=[])
    assert dashboard_render.render_csv(data).strip() == '"case_id"'


# --- Responsible AI log -----------------------------------------------------


def test_log_includes_edited_and_rejected_but_not_accepted():
    cases = [_case("NS-001"), _case("NS-002"), _case("NS-003")]
    records = [_record("NS-001"), _record("NS-002"), _record("NS-003")]
    reviews = [
        Review("RUN-1", "NS-001", ACCEPTED, "alice", "t"),
        Review("RUN-1", "NS-002", EDITED, "alice", "t", corrected_root_cause="acl_rule_order", reason="close"),
        Review("RUN-1", "NS-003", REJECTED, "bob", "t", failure_mode="overconfident", reason="wrong"),
    ]
    data = _build(cases=cases, records=records, reviews=reviews)
    log = dashboard_render.render_responsible_ai_log(data, reviews, "RUN-1")

    assert "NS-002" in log and "NS-003" in log
    assert "### NS-001" not in log  # Accepted is not a correction
    assert "2 corrected case(s)" in log


def test_log_leaves_human_judgement_fields_as_todo():
    reviews = [Review("RUN-1", "NS-021", REJECTED, "bob", "t", failure_mode="overconfident", reason="wrong")]
    log = dashboard_render.render_responsible_ai_log(_build(reviews=reviews), reviews, "RUN-1")

    assert "**Why it matters:** TODO" in log
    assert "**Mitigation applied:** TODO" in log
    assert "wrong" in log  # the reviewer's real reason is carried through


def test_log_warns_when_under_five_corrections():
    reviews = [Review("RUN-1", "NS-021", REJECTED, "bob", "t", failure_mode="overconfident", reason="w")]
    log = dashboard_render.render_responsible_ai_log(_build(reviews=reviews), reviews, "RUN-1")
    assert "HR-06" in log
    assert "Only 1 correction(s)" in log


def test_log_handles_an_edited_verdict_with_no_failure_mode():
    # §2.4 makes failure_mode optional on Edited; the generator must not assume it is present.
    reviews = [Review("RUN-1", "NS-021", EDITED, "alice", "t", corrected_root_cause="acl_rule_order", reason="close")]
    log = dashboard_render.render_responsible_ai_log(_build(reviews=reviews), reviews, "RUN-1")
    assert "not recorded" in log
    assert "acl_rule_order" in log

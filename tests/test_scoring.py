"""Scoring unit tests — synthetic Diagnosis objects, no LLM and no fixtures.

These validate the formulas in docs/ai_diagnosis_specification.md §6 at their boundaries.
"""

from netsage.ai.schema import Diagnosis, EvidenceItem
from netsage.cases import Case
from netsage.scoring import aggregate, score_case


def _case(expected_root_cause="acl_wrong_direction", osi_layer="L3/L4", next_command="show access-lists 110"):
    return Case(
        case_id="NS-021",
        title="t",
        category="ACL",
        concept_tag="c",
        symptom="s",
        topology_note="t",
        show_outputs="R1# show access-lists 110",
        expected_fault="f",
        expected_root_cause=expected_root_cause,
        osi_layer=osi_layer,
        severity="High",
        expected_next_command=next_command,
        expected_fix_steps="fix",
        source_lab="lab.pkt",
        difficulty="Medium",
    )


def _diagnosis(tag="acl_wrong_direction", osi="L3/L4", band="high", confidence=0.82, next_command=None):
    return Diagnosis(
        case_id="NS-021",
        root_cause="r",
        root_cause_tag=tag,
        osi_layer=osi,
        confidence=confidence,
        confidence_band=band,
        evidence=[EvidenceItem(quote="q", source="show_outputs", why="w")],
        next_command=next_command if next_command is not None else ["show access-lists 110"],
        fix_steps=["f"],
        verification_steps=["v"],
        risk_notes="r",
        requires_human_review=True,
    )


# --- root_cause_match -------------------------------------------------------


def test_root_cause_match_is_exact_string_equality():
    assert score_case(_diagnosis(tag="acl_wrong_direction"), _case(), []).root_cause_match is True
    assert score_case(_diagnosis(tag="acl_wrong_interface"), _case(), []).root_cause_match is False


def test_root_cause_match_is_not_fuzzy():
    # A near-miss tag is still a miss — the spec says exact string.
    assert score_case(_diagnosis(tag="acl_misconfiguration"), _case(), []).root_cause_match is False


# --- osi_match --------------------------------------------------------------


def test_osi_match_on_exact_layer():
    assert score_case(_diagnosis(osi="L3/L4"), _case(osi_layer="L3/L4"), []).osi_match is True


def test_osi_match_on_partial_token_overlap():
    # The spec's own example: L3/L4 vs L4 counts as a match.
    assert score_case(_diagnosis(osi="L4"), _case(osi_layer="L3/L4"), []).osi_match is True
    assert score_case(_diagnosis(osi="L3/L4"), _case(osi_layer="L3"), []).osi_match is True


def test_osi_match_false_on_disjoint_layers():
    # The spec's own counter-example: L2 vs L7 does not match.
    assert score_case(_diagnosis(osi="L2"), _case(osi_layer="L7"), []).osi_match is False
    assert score_case(_diagnosis(osi="L1/L2"), _case(osi_layer="L4/L7"), []).osi_match is False


# --- next_command_match -----------------------------------------------------


def test_next_command_match_ignores_case_and_whitespace():
    diagnosis = _diagnosis(next_command=["SHOW   access-lists    110"])
    assert score_case(diagnosis, _case(next_command="show access-lists 110"), []).next_command_match is True


def test_next_command_match_strips_trailing_pipe_filter():
    diagnosis = _diagnosis(next_command=["show ip interface Gi0/0.99"])
    case = _case(next_command="show ip interface Gi0/0.99 | include access list")
    assert score_case(diagnosis, case, []).next_command_match is True


def test_next_command_match_preserves_host_commands_without_pipes():
    # 'ipconfig /all on PC5' appears verbatim in the real dataset — normalisation must not eat it.
    diagnosis = _diagnosis(next_command=["ipconfig /all on PC5"])
    assert score_case(diagnosis, _case(next_command="ipconfig /all on PC5"), []).next_command_match is True


def test_next_command_match_when_expected_appears_anywhere_in_the_list():
    diagnosis = _diagnosis(next_command=["show running-config", "show access-lists 110", "show ip route"])
    assert score_case(diagnosis, _case(next_command="show access-lists 110"), []).next_command_match is True


def test_next_command_match_false_when_absent():
    diagnosis = _diagnosis(next_command=["show ip route"])
    assert score_case(diagnosis, _case(next_command="show access-lists 110"), []).next_command_match is False


# --- evidence_grounded ------------------------------------------------------


def test_evidence_grounded_reflects_the_hallucination_flag():
    assert score_case(_diagnosis(), _case(), []).evidence_grounded is True
    assert score_case(_diagnosis(), _case(), ["hallucinated_evidence"]).evidence_grounded is False


# --- abstained / confidently_wrong ------------------------------------------


def test_abstained_when_tag_is_insufficient_evidence():
    scores = score_case(_diagnosis(tag="insufficient_evidence", band="low", confidence=0.2), _case(), [])
    assert scores.abstained is True
    assert scores.root_cause_match is False


def test_confidently_wrong_requires_high_band_and_a_miss():
    # high + wrong  -> True   (the headline safety metric)
    assert score_case(_diagnosis(tag="wrong_tag", band="high"), _case(), []).confidently_wrong is True
    # high + right  -> False
    assert score_case(_diagnosis(tag="acl_wrong_direction", band="high"), _case(), []).confidently_wrong is False
    # low  + wrong  -> False (an inconvenience, not a safety failure)
    assert score_case(_diagnosis(tag="wrong_tag", band="low", confidence=0.2), _case(), []).confidently_wrong is False
    # medium + wrong -> False
    assert score_case(_diagnosis(tag="wrong_tag", band="medium", confidence=0.5), _case(), []).confidently_wrong is False


# --- aggregate --------------------------------------------------------------


def _record(case_id, status="ok", **score_overrides):
    scores = {
        "root_cause_match": False,
        "osi_match": False,
        "next_command_match": False,
        "evidence_grounded": True,
        "abstained": False,
        "confidently_wrong": False,
    }
    scores.update(score_overrides)
    return {"case_id": case_id, "status": status, "scores": scores if status == "ok" else None}


def test_aggregate_excludes_abstentions_from_the_accuracy_denominator():
    records = [
        _record("NS-001", root_cause_match=True, osi_match=True),
        _record("NS-002", root_cause_match=True, osi_match=True),
        _record("NS-003", abstained=True),
        _record("NS-004"),
    ]
    metrics = aggregate(records)

    assert metrics.total == 4
    assert metrics.abstained == 1
    assert metrics.answered == 3  # 4 - 1 abstained
    assert metrics.root_cause_accuracy == 2 / 3
    assert metrics.osi_accuracy == 2 / 3
    assert metrics.abstain_rate == 1 / 4


def test_aggregate_grounding_rate_uses_the_full_total():
    records = [_record("NS-001"), _record("NS-002", evidence_grounded=False)]
    assert aggregate(records).grounding_rate == 0.5


def test_aggregate_counts_failed_cases_in_total_but_not_as_matches():
    records = [
        _record("NS-001", root_cause_match=True),
        _record("NS-002", status="parse_failed"),
        _record("NS-003", status="backend_error"),
    ]
    metrics = aggregate(records)

    assert metrics.total == 3
    assert metrics.parse_failed == 1
    assert metrics.backend_error == 1
    assert metrics.root_cause_match == 1
    assert metrics.root_cause_accuracy == 1 / 3  # failures drag accuracy down, not excluded
    assert metrics.evidence_grounded == 1
    assert metrics.grounding_rate == 1 / 3


def test_aggregate_lists_confidently_wrong_case_ids():
    records = [
        _record("NS-001", confidently_wrong=True),
        _record("NS-002"),
        _record("NS-003", confidently_wrong=True),
    ]
    metrics = aggregate(records)
    assert metrics.confidently_wrong == 2
    assert metrics.confidently_wrong_cases == ["NS-001", "NS-003"]


def test_aggregate_accuracy_is_none_when_every_case_abstained():
    # Guards against a ZeroDivisionError, and reports "no answered cases" rather than a fake 0%.
    metrics = aggregate([_record("NS-001", abstained=True)])
    assert metrics.answered == 0
    assert metrics.root_cause_accuracy is None
    assert metrics.osi_accuracy is None


def test_aggregate_of_an_empty_run_is_safe():
    metrics = aggregate([])
    assert metrics.total == 0
    assert metrics.root_cause_accuracy is None
    assert metrics.grounding_rate == 0.0


def test_next_command_has_its_own_denominator_not_the_accuracy_one():
    """Regression: next_command_match counts abstained cases (the abstain path legitimately
    proposes disambiguating commands), so sharing `answered` could print "1/0"."""
    records = [_record("NS-001", abstained=True, next_command_match=True)]
    metrics = aggregate(records)

    assert metrics.answered == 0  # the accuracy denominator
    assert metrics.scored == 1  # the next-command denominator
    assert metrics.next_command_match == 1


def test_scored_excludes_failed_cases():
    records = [_record("NS-001"), _record("NS-002", status="parse_failed")]
    metrics = aggregate(records)
    assert metrics.total == 2
    assert metrics.scored == 1

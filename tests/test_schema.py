"""Tests parse_diagnosis() against literal JSON strings — no LLM call anywhere in this file."""

import json

from netsage.ai.schema import parse_diagnosis
from netsage.cases import Case
from netsage.rules.base import Finding

SHOW_OUTPUTS = (
    "R1# show access-lists 110\nExtended IP access list 110\n"
    " 10 deny ip 10.10.30.0 0.0.0.255 10.10.99.0 0.0.0.255 (0 matches)\n"
    "R1# show ip interface Gi0/0.99 | include access list\n  Inbound  access list is 110\n"
)


def _case() -> Case:
    return Case(
        case_id="NS-021",
        title="ACL applied in the wrong direction",
        category="ACL",
        concept_tag="acl-direction",
        symptom="Guest VLAN traffic is not blocked from the server VLAN.",
        topology_note="ACL 110 is applied on R1 Gi0/0.99.",
        show_outputs=SHOW_OUTPUTS,
        expected_fault="ACL applied inbound on the wrong subinterface.",
        expected_root_cause="acl_wrong_direction",
        osi_layer="L3/L4",
        severity="High",
        expected_next_command="show ip interface Gi0/0.99 | include access list",
        expected_fix_steps="Move the ACL to the correct subinterface.",
        source_lab="lab-acl.pkt",
        difficulty="Medium",
    )


def _valid_diagnosis_dict(**overrides) -> dict:
    diagnosis = {
        "case_id": "NS-021",
        "root_cause": "The ACL is applied inbound on the server subinterface instead of the guest one.",
        "root_cause_tag": "acl_wrong_direction",
        "osi_layer": "L3/L4",
        "confidence": 0.82,
        "confidence_band": "high",
        "evidence": [
            {
                "quote": "10 deny ip 10.10.30.0 0.0.0.255 10.10.99.0 0.0.0.255 (0 matches)",
                "source": "show_outputs",
                "why": "The deny line never matches, meaning guest traffic never reaches it.",
            },
            {
                "quote": "Inbound  access list is 110",
                "source": "show_outputs",
                "why": "The ACL is bound inbound on the wrong subinterface.",
            },
        ],
        "next_command": ["show ip interface Gi0/0.99 | include access list"],
        "fix_steps": ["Remove the ACL from Gi0/0.99", "Apply it inbound on Gi0/0.30 instead"],
        "verification_steps": ["Re-test from a guest host", "Confirm the deny line increments"],
        "risk_notes": "Applying it outbound on the server side would also filter return traffic.",
        "requires_human_review": True,
    }
    diagnosis.update(overrides)
    return diagnosis


def test_valid_diagnosis_parses_ok_with_no_flags():
    result = parse_diagnosis(json.dumps(_valid_diagnosis_dict()), _case())
    assert result.status == "ok"
    assert result.flags == []
    assert result.errors == []
    assert result.diagnosis.root_cause_tag == "acl_wrong_direction"
    assert result.diagnosis.requires_human_review is True


def test_markdown_fenced_json_is_stripped_before_parsing():
    raw = "```json\n" + json.dumps(_valid_diagnosis_dict()) + "\n```"
    result = parse_diagnosis(raw, _case())
    assert result.status == "ok"


def test_requires_human_review_is_hardcoded_true_even_if_model_says_false():
    result = parse_diagnosis(json.dumps(_valid_diagnosis_dict(requires_human_review=False)), _case())
    assert result.status == "ok"
    assert result.diagnosis.requires_human_review is True


def test_requires_human_review_may_be_absent_entirely():
    data = _valid_diagnosis_dict()
    del data["requires_human_review"]
    result = parse_diagnosis(json.dumps(data), _case())
    assert result.status == "ok"
    assert result.diagnosis.requires_human_review is True


def test_invalid_json_is_parse_failed():
    result = parse_diagnosis("{not json", _case())
    assert result.status == "parse_failed"
    assert result.diagnosis is None
    assert result.raw_response == "{not json"


def test_non_object_json_is_schema_invalid():
    result = parse_diagnosis("[1, 2, 3]", _case())
    assert result.status == "schema_invalid"


def test_unknown_field_is_schema_invalid():
    result = parse_diagnosis(json.dumps(_valid_diagnosis_dict(extra_field="surprise")), _case())
    assert result.status == "schema_invalid"
    assert any("unknown field" in e for e in result.errors)


def test_missing_required_field_is_schema_invalid():
    data = _valid_diagnosis_dict()
    del data["risk_notes"]
    result = parse_diagnosis(json.dumps(data), _case())
    assert result.status == "schema_invalid"
    assert any("missing required field" in e for e in result.errors)


def test_invalid_osi_layer_is_schema_invalid():
    result = parse_diagnosis(json.dumps(_valid_diagnosis_dict(osi_layer="L99")), _case())
    assert result.status == "schema_invalid"


def test_confidence_band_mismatch_is_schema_invalid():
    result = parse_diagnosis(json.dumps(_valid_diagnosis_dict(confidence=0.2, confidence_band="high")), _case())
    assert result.status == "schema_invalid"
    assert any("does not match" in e for e in result.errors)


def test_confidence_band_boundaries_are_inclusive_on_the_low_side():
    # 0.4 and 0.75 are documented as the medium band's own boundaries, not high/low.
    result = parse_diagnosis(json.dumps(_valid_diagnosis_dict(confidence=0.4, confidence_band="medium")), _case())
    assert result.status == "ok"
    result = parse_diagnosis(json.dumps(_valid_diagnosis_dict(confidence=0.75, confidence_band="medium")), _case())
    assert result.status == "ok"


def test_confidence_out_of_range_is_schema_invalid():
    result = parse_diagnosis(json.dumps(_valid_diagnosis_dict(confidence=1.5)), _case())
    assert result.status == "schema_invalid"


def test_empty_evidence_with_non_abstain_tag_is_schema_invalid():
    result = parse_diagnosis(json.dumps(_valid_diagnosis_dict(evidence=[])), _case())
    assert result.status == "schema_invalid"


def test_empty_evidence_with_abstain_tag_is_ok_and_flagged_abstained():
    data = _valid_diagnosis_dict(
        evidence=[],
        root_cause_tag="insufficient_evidence",
        confidence=0.2,
        confidence_band="low",
    )
    result = parse_diagnosis(json.dumps(data), _case())
    assert result.status == "ok"
    assert "abstained" in result.flags


def test_too_many_evidence_items_is_schema_invalid():
    item = _valid_diagnosis_dict()["evidence"][0]
    result = parse_diagnosis(json.dumps(_valid_diagnosis_dict(evidence=[item] * 5)), _case())
    assert result.status == "schema_invalid"


def test_evidence_source_not_in_vocabulary_is_schema_invalid():
    data = _valid_diagnosis_dict()
    data["evidence"][0]["source"] = "packet_capture"
    result = parse_diagnosis(json.dumps(data), _case())
    assert result.status == "schema_invalid"


def test_hallucinated_evidence_quote_is_flagged_not_rejected():
    data = _valid_diagnosis_dict()
    data["evidence"][0]["quote"] = "this line was never in the show output"
    result = parse_diagnosis(json.dumps(data), _case())
    assert result.status == "ok"
    assert "hallucinated_evidence" in result.flags
    assert result.diagnosis is not None  # kept, just flagged — grounding failure never rejects


def test_evidence_quote_survives_whitespace_reflow():
    data = _valid_diagnosis_dict()
    data["evidence"][0]["quote"] = "10   deny ip   10.10.30.0 0.0.0.255 10.10.99.0 0.0.0.255   (0 matches)"
    result = parse_diagnosis(json.dumps(data), _case())
    assert result.status == "ok"
    assert "hallucinated_evidence" not in result.flags


def test_unknown_root_cause_tag_is_flagged_not_rejected():
    result = parse_diagnosis(json.dumps(_valid_diagnosis_dict(root_cause_tag="made_up_tag")), _case())
    assert result.status == "ok"
    assert "unknown_tag" in result.flags


def test_rule_conflict_flagged_when_abstaining_despite_high_finding():
    data = _valid_diagnosis_dict(
        evidence=[],
        root_cause_tag="insufficient_evidence",
        confidence=0.2,
        confidence_band="low",
    )
    high_finding = Finding(rule_id="R11_acl_zero_match", severity="HIGH", message="m", evidence="e")
    result = parse_diagnosis(json.dumps(data), _case(), rule_findings=[high_finding])
    assert "rule_conflict" in result.flags


def test_no_rule_conflict_when_no_high_findings_exist():
    data = _valid_diagnosis_dict(
        evidence=[],
        root_cause_tag="insufficient_evidence",
        confidence=0.2,
        confidence_band="low",
    )
    info_finding = Finding(rule_id="R06_trunk_vlan_pruned", severity="INFO", message="m", evidence="e")
    result = parse_diagnosis(json.dumps(data), _case(), rule_findings=[info_finding])
    assert "rule_conflict" not in result.flags

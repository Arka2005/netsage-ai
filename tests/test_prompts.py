from netsage.ai.prompts import build_prompt, build_repair_message, load_prompt_file, render_case_block
from netsage.cases import Case
from netsage.rules.base import Finding


def _case() -> Case:
    return Case(
        case_id="NS-021",
        title="ACL applied in the wrong direction",
        category="ACL",
        concept_tag="acl-direction",
        symptom="Guest VLAN traffic is not blocked from the server VLAN.",
        topology_note="ACL 110 is applied on R1 Gi0/0.99.",
        show_outputs="R1# show access-lists 110\n 10 deny ip 10.10.30.0 0.0.0.255 10.10.99.0 0.0.0.255 (0 matches)",
        expected_fault="ACL applied inbound on the wrong subinterface.",
        expected_root_cause="acl_wrong_direction",
        osi_layer="L3/L4",
        severity="High",
        expected_next_command="show ip interface Gi0/0.99 | include access list",
        expected_fix_steps="Move the ACL to the correct subinterface.",
        source_lab="lab-acl.pkt",
        difficulty="Medium",
    )


def test_load_prompt_file_parses_front_matter(tmp_path):
    path = tmp_path / "p.md"
    path.write_text("---\nprompt_version: v9.9\nupdated: 2026-01-01\n---\nbody text here\n", encoding="utf-8")
    prompt_file = load_prompt_file(str(path))
    assert prompt_file.prompt_version == "v9.9"
    assert prompt_file.body == "body text here"


def test_load_prompt_file_handles_missing_front_matter(tmp_path):
    path = tmp_path / "p.md"
    path.write_text("just a body, no front matter", encoding="utf-8")
    prompt_file = load_prompt_file(str(path))
    assert prompt_file.prompt_version == "unknown"
    assert prompt_file.body == "just a body, no front matter"


def test_render_case_block_includes_rule_findings():
    finding = Finding(rule_id="R11_acl_zero_match", severity="HIGH", message="m", evidence="e")
    block = render_case_block(_case(), [finding])
    assert "case_id: NS-021" in block
    assert "R11_acl_zero_match [HIGH]: m" in block
    assert 'evidence: "e"' in block
    assert "## TASK" in block


def test_render_case_block_shows_none_when_no_findings():
    block = render_case_block(_case(), [])
    assert "(none)" in block


def test_build_prompt_uses_real_prompt_files_and_embeds_case():
    system, user, prompt_version = build_prompt(_case(), [], prompts_dir="prompts")

    assert "senior network engineer" in system
    assert "requires_human_review" in system
    assert prompt_version == "v1.0"
    # the three few-shot examples are present
    assert "EXAMPLE 1" in user
    assert "EXAMPLE 2" in user
    assert "EXAMPLE 3" in user
    assert "insufficient_evidence" in user
    # and the real case is appended at the end
    assert "case_id: NS-021" in user
    assert user.rindex("case_id: NS-021") > user.index("EXAMPLE 3")


def test_build_repair_message_substitutes_parser_error():
    message = build_repair_message("previous user text", "Expecting ',' delimiter", prompts_dir="prompts")
    assert "previous user text" in message
    assert "Expecting ',' delimiter" in message
    assert "{{parser_error}}" not in message

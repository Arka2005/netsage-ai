from netsage.cases import (
    REQUIRED_FIELDS,
    SchemaError,
    load_cases,
    validate_cases,
)


def test_prompt_context_excludes_ground_truth(tmp_cases_csv):
    cases = load_cases(tmp_cases_csv)
    case = cases[0]
    ctx = case.to_prompt_context()
    gt = case.ground_truth()

    assert set(ctx) == {"case_id", "symptom", "topology_note", "show_outputs"}
    assert set(gt) == {
        "expected_fault",
        "expected_root_cause",
        "osi_layer",
        "expected_next_command",
        "expected_fix_steps",
    }
    assert not any(v and v in ctx.values() for v in gt.values())


def test_load_cases_handles_multiline_show_outputs(tmp_cases_csv):
    cases = load_cases(tmp_cases_csv)
    assert len(cases) == 2
    assert "\n" in cases[0].show_outputs
    assert cases[0].case_id == "NS-001"
    assert cases[1].case_id == "NS-002"


def test_load_cases_raises_schema_error_on_wrong_header(tmp_path, write_cases_csv, make_case_row):
    bad_header = [f for f in REQUIRED_FIELDS if f != "difficulty"]  # missing a column
    path = write_cases_csv(tmp_path / "bad.csv", [make_case_row()], header=bad_header)
    try:
        load_cases(path)
        assert False, "expected SchemaError"
    except SchemaError:
        pass


def test_load_cases_raises_file_not_found_for_missing_path():
    try:
        load_cases("does/not/exist.csv")
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_valid_dataset_passes_validation(tmp_cases_csv):
    report = validate_cases(load_cases(tmp_cases_csv))
    assert report.valid
    assert report.errors == []
    assert report.case_count == 2
    assert report.category_counts == {"VLAN": 2}


def test_duplicate_case_id_is_error(tmp_path, write_cases_csv, make_case_row):
    rows = [make_case_row(), make_case_row()]  # both NS-001
    path = write_cases_csv(tmp_path / "dup.csv", rows)
    report = validate_cases(load_cases(path))
    assert not report.valid
    assert any("duplicate case_id" in e for e in report.errors)


def test_bad_case_id_format_is_error(tmp_path, write_cases_csv, make_case_row):
    path = write_cases_csv(tmp_path / "badid.csv", [make_case_row(case_id="NS-1")])
    report = validate_cases(load_cases(path))
    assert not report.valid
    assert any("does not match" in e for e in report.errors)


def test_blank_required_field_is_error(tmp_path, write_cases_csv, make_case_row):
    path = write_cases_csv(tmp_path / "blank.csv", [make_case_row(symptom="")])
    report = validate_cases(load_cases(path))
    assert not report.valid
    assert any("'symptom' is blank" in e for e in report.errors)


def test_unknown_enum_value_is_error(tmp_path, write_cases_csv, make_case_row):
    path = write_cases_csv(tmp_path / "badenum.csv", [make_case_row(severity="Extreme")])
    report = validate_cases(load_cases(path))
    assert not report.valid
    assert any("unknown severity" in e for e in report.errors)


def test_unknown_root_cause_tag_is_error(tmp_path, write_cases_csv, make_case_row):
    path = write_cases_csv(tmp_path / "badtag.csv", [make_case_row(expected_root_cause="made_up_tag")])
    report = validate_cases(load_cases(path))
    assert not report.valid
    assert any("unknown expected_root_cause" in e for e in report.errors)


def test_insufficient_evidence_is_a_valid_root_cause_tag(tmp_path, write_cases_csv, make_case_row):
    # Reserved abstain tag — also a legitimate ground truth for a healthy control case.
    path = write_cases_csv(tmp_path / "healthy.csv", [make_case_row(expected_root_cause="insufficient_evidence")])
    report = validate_cases(load_cases(path))
    assert report.valid


def test_short_show_outputs_is_error(tmp_path, write_cases_csv, make_case_row):
    path = write_cases_csv(tmp_path / "short.csv", [make_case_row(show_outputs="R1# show ip route\ntoo short")])
    report = validate_cases(load_cases(path))
    assert not report.valid
    assert any("shorter than 80" in e for e in report.errors)


def test_show_outputs_missing_prompt_line_is_error(tmp_path, write_cases_csv, make_case_row):
    no_prompt = "just some plain text output with no device prompt line at all, padded out past eighty characters"
    path = write_cases_csv(tmp_path / "noprompt.csv", [make_case_row(show_outputs=no_prompt)])
    report = validate_cases(load_cases(path))
    assert not report.valid
    assert any("no '<DEVICE>" in e for e in report.errors)


def test_host_only_prompt_line_is_accepted(tmp_path, write_cases_csv, make_case_row):
    # Host-side cases legitimately use "PC1>" rather than a "#" IOS prompt. (dataset spec §6 rule 5)
    host_output = "PC1> ipconfig /all\nIP Address..............: 169.254.12.34\nSubnet Mask..............: 255.255.0.0"
    path = write_cases_csv(tmp_path / "host.csv", [make_case_row(show_outputs=host_output)])
    report = validate_cases(load_cases(path))
    assert report.valid


def test_brief_mandated_family_under_three_cases_warns_not_errors(tmp_path, write_cases_csv, make_case_row):
    rows = [make_case_row(case_id="NS-001", category="DNS"), make_case_row(case_id="NS-002", category="DNS")]
    path = write_cases_csv(tmp_path / "underfamily.csv", rows)
    report = validate_cases(load_cases(path))
    assert report.valid  # a warning, not an error
    assert any("'DNS' has fewer than 3 cases" in w for w in report.warnings)


def test_switching_family_under_three_cases_does_not_warn(tmp_path, write_cases_csv, make_case_row):
    # Switching/Physical are not brief-mandated families (dataset spec §4) — 2 cases is expected.
    rows = [make_case_row(case_id="NS-001", category="Switching"), make_case_row(case_id="NS-002", category="Switching")]
    path = write_cases_csv(tmp_path / "switching.csv", rows)
    report = validate_cases(load_cases(path))
    assert report.valid
    assert not any("Switching" in w for w in report.warnings)

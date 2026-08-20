from netsage import cli


def test_validate_passes_on_good_dataset_and_prints_documented_format(capsys, tmp_cases_csv):
    exit_code = cli.main(["validate", "--path", tmp_cases_csv])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "2 cases loaded from" in out
    assert "schema OK" in out
    assert "case_id unique" in out
    assert "coverage:" in out
    assert "VLAN 2" in out
    assert "severity:" in out


def test_validate_exits_2_on_missing_file(capsys):
    exit_code = cli.main(["validate", "--path", "does/not/exist.csv"])
    out = capsys.readouterr().out

    assert exit_code == 2
    assert "not found" in out


def test_validate_exits_1_on_schema_violation(capsys, tmp_path, write_cases_csv, make_case_row):
    from netsage.cases import REQUIRED_FIELDS

    bad_header = [f for f in REQUIRED_FIELDS if f != "difficulty"]
    path = write_cases_csv(tmp_path / "bad.csv", [make_case_row()], header=bad_header)

    exit_code = cli.main(["validate", "--path", path])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "schema violation" in out


def test_validate_exits_1_on_row_level_error(capsys, tmp_path, write_cases_csv, make_case_row):
    path = write_cases_csv(tmp_path / "bad.csv", [make_case_row(severity="Extreme")])

    exit_code = cli.main(["validate", "--path", path])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "unknown severity" in out


def test_validate_prints_warning_for_thin_brief_family(capsys, tmp_path, write_cases_csv, make_case_row):
    rows = [make_case_row(case_id="NS-001", category="DNS"), make_case_row(case_id="NS-002", category="DNS")]
    path = write_cases_csv(tmp_path / "thin.csv", rows)

    exit_code = cli.main(["validate", "--path", path])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "'DNS' has fewer than 3 cases" in out

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


def test_check_case_prints_findings(capsys, tmp_path, write_cases_csv, make_case_row):
    acl_output = (
        "R1# show access-lists 110\nExtended IP access list 110\n"
        " 10 deny ip 10.10.30.0 0.0.0.255 10.10.99.0 0.0.0.255 (0 matches)\n\n"
        "R1# show ip interface Gi0/0.99 | include access list\n  Inbound  access list is 110\n"
    )
    path = write_cases_csv(tmp_path / "acl.csv", [make_case_row(case_id="NS-001", show_outputs=acl_output)])

    exit_code = cli.main(["check", "--case", "NS-001", "--dataset", path])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "R11_acl_zero_match" in out
    assert "2 findings" in out


def test_check_case_not_found_exits_1(capsys, tmp_cases_csv):
    exit_code = cli.main(["check", "--case", "NS-999", "--dataset", tmp_cases_csv])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "not found" in out


def test_check_all_prints_hit_table(capsys, tmp_cases_csv):
    exit_code = cli.main(["check", "--all", "--dataset", tmp_cases_csv])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Rule hit table" in out
    assert "R11_acl_zero_match" in out
    assert "2 cases checked · 0 rule engine error(s)" in out


def test_validate_exits_2_on_unreadable_path(capsys, tmp_path):
    # A directory isn't a file — used to raise an uncaught PermissionError/IsADirectoryError.
    exit_code = cli.main(["validate", "--path", str(tmp_path)])
    out = capsys.readouterr().out

    assert exit_code == 2
    assert "unreadable" in out


def test_validate_exits_2_on_non_utf8_file(capsys, tmp_path):
    path = tmp_path / "cp1252.csv"
    path.write_bytes("café".encode("cp1252"))  # not valid UTF-8

    exit_code = cli.main(["validate", "--path", str(path)])
    out = capsys.readouterr().out

    assert exit_code == 2
    assert "unreadable" in out


def test_check_exits_2_not_1_on_missing_dataset(capsys):
    # check's exit 1 is documented as "case not found" — a missing dataset must not collide with it.
    exit_code = cli.main(["check", "--all", "--dataset", "does/not/exist.csv"])
    assert exit_code == 2


def test_check_exits_2_not_1_on_schema_violation(capsys, tmp_path, write_cases_csv, make_case_row):
    from netsage.cases import REQUIRED_FIELDS

    bad_header = [f for f in REQUIRED_FIELDS if f != "difficulty"]
    path = write_cases_csv(tmp_path / "bad.csv", [make_case_row()], header=bad_header)

    exit_code = cli.main(["check", "--all", "--dataset", path])
    assert exit_code == 2


def test_check_case_not_found_still_exits_1_after_remap(capsys, tmp_cases_csv):
    exit_code = cli.main(["check", "--case", "NS-999", "--dataset", tmp_cases_csv])
    assert exit_code == 1

import json

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


def _acl_case_row(make_case_row, case_id="NS-021"):
    """An ACL row whose ground truth matches what the committed NS-021 fixture answers, so the
    wiring test exercises a real scoring match rather than an incidental mismatch."""
    acl_output = (
        "R1# show access-lists 110\nExtended IP access list 110\n"
        " 10 deny ip 10.10.30.0 0.0.0.255 10.10.99.0 0.0.0.255 (0 matches)\n\n"
        "R1# show ip interface Gi0/0.99 | include access list\n  Inbound  access list is 110\n"
    )
    return make_case_row(
        case_id=case_id,
        show_outputs=acl_output,
        category="ACL",
        expected_root_cause="acl_wrong_direction",
        osi_layer="L3/L4",
        expected_next_command="show ip interface Gi0/0.99 | include access list",
    )


def test_run_case_with_mock_backend_writes_ok_record(capsys, tmp_path, write_cases_csv, make_case_row):
    dataset_path = write_cases_csv(tmp_path / "cases.csv", [_acl_case_row(make_case_row)])
    runs_dir = tmp_path / "runs"

    exit_code = cli.main(
        ["run", "--backend", "mock", "--case", "NS-021", "--dataset", dataset_path, "--runs-dir", str(runs_dir)]
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "PENDING HUMAN REVIEW" in out
    assert "root cause match   1/1" in out  # documented run summary [functional_specification.md §2.3]

    jsonl_files = list(runs_dir.glob("*.jsonl"))
    assert len(jsonl_files) == 1
    record = json.loads(jsonl_files[0].read_text(encoding="utf-8").strip())

    assert record["status"] == "ok"
    assert record["case_id"] == "NS-021"
    assert record["diagnosis"]["root_cause_tag"] == "acl_wrong_direction"
    assert record["review"] is None
    # scores are populated for ok records as of Phase 8 [FR-05]
    assert record["scores"]["root_cause_match"] is True
    assert record["scores"]["evidence_grounded"] is True
    assert record["scores"]["abstained"] is False
    assert "raw_response" in record and record["raw_response"]  # stored verbatim
    assert len(record["rule_findings"]) == 2  # R11 fires twice on this evidence


def test_run_all_processes_every_case(capsys, tmp_path, write_cases_csv, make_case_row):
    # Uses the real committed fixtures for NS-021 and NS-022 (the default --fixtures-dir).
    rows = [_acl_case_row(make_case_row, case_id="NS-021"), _acl_case_row(make_case_row, case_id="NS-022")]
    dataset_path = write_cases_csv(tmp_path / "cases.csv", rows)
    runs_dir = tmp_path / "runs"

    exit_code = cli.main(
        ["run", "--backend", "mock", "--all", "--dataset", dataset_path, "--runs-dir", str(runs_dir)]
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "root cause match" in out  # the documented run summary [functional_specification.md §2.3]
    assert "evidence grounded" in out
    assert "confidently wrong" in out
    lines = (runs_dir / next(runs_dir.glob("*.jsonl")).name).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_run_missing_fixture_reports_backend_error(capsys, tmp_path, write_cases_csv, make_case_row):
    dataset_path = write_cases_csv(tmp_path / "cases.csv", [make_case_row(case_id="NS-001")])
    runs_dir = tmp_path / "runs"
    fixtures_dir = tmp_path / "empty_fixtures"
    fixtures_dir.mkdir()

    exit_code = cli.main(
        [
            "run",
            "--backend",
            "mock",
            "--case",
            "NS-001",
            "--dataset",
            dataset_path,
            "--runs-dir",
            str(runs_dir),
            "--fixtures-dir",
            str(fixtures_dir),
        ]
    )

    assert exit_code == 0  # the command completes; the failure is recorded per-case, not fatal
    record = json.loads((runs_dir / next(runs_dir.glob("*.jsonl")).name).read_text(encoding="utf-8").strip())
    assert record["status"] == "backend_error"
    assert record["diagnosis"] is None


def test_run_retries_once_on_malformed_json_then_gives_up(capsys, tmp_path, write_cases_csv, make_case_row):
    dataset_path = write_cases_csv(tmp_path / "cases.csv", [make_case_row(case_id="NS-001")])
    runs_dir = tmp_path / "runs"
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "NS-001.json").write_text("this is not valid json", encoding="utf-8")

    exit_code = cli.main(
        [
            "run",
            "--backend",
            "mock",
            "--case",
            "NS-001",
            "--dataset",
            dataset_path,
            "--runs-dir",
            str(runs_dir),
            "--fixtures-dir",
            str(fixtures_dir),
        ]
    )

    assert exit_code == 0
    record = json.loads((runs_dir / next(runs_dir.glob("*.jsonl")).name).read_text(encoding="utf-8").strip())
    assert record["status"] == "parse_failed"
    assert record["raw_response"] == "this is not valid json"


def test_run_unimplemented_backend_exits_4(capsys, tmp_cases_csv, tmp_path):
    exit_code = cli.main(
        ["run", "--backend", "api", "--case", "NS-001", "--dataset", tmp_cases_csv, "--runs-dir", str(tmp_path)]
    )
    out = capsys.readouterr().out

    assert exit_code == 4
    assert "isn't implemented" in out


def test_run_id_sanitises_colons_in_model_names():
    """Regression: Ollama model names always contain a colon ("gemma3:4b"). On Windows a colon
    in a path silently opens an NTFS alternate data stream, so the run JSONL vanished into a
    hidden stream and the visible artifact was 0 bytes — losing the audit trail [FR-07]."""
    run_id = cli._make_run_id("ollama", "gemma3:4b", "v1.1")
    assert ":" not in run_id
    assert run_id.endswith("-ollama-gemma3-4b-v1.1")


def test_run_writes_a_readable_artifact_for_a_colon_model_name(tmp_path, write_cases_csv, make_case_row):
    dataset_path = write_cases_csv(tmp_path / "cases.csv", [_acl_case_row(make_case_row)])
    runs_dir = tmp_path / "runs"

    exit_code = cli.main(
        [
            "run",
            "--backend",
            "mock",
            "--model",
            "gemma3:4b",  # colon, as every real ollama model has
            "--case",
            "NS-021",
            "--dataset",
            dataset_path,
            "--runs-dir",
            str(runs_dir),
        ]
    )

    assert exit_code == 0
    written = list(runs_dir.glob("*.jsonl"))
    assert len(written) == 1, f"expected one readable .jsonl, found {[p.name for p in runs_dir.iterdir()]}"
    assert written[0].stat().st_size > 0, "artifact is empty — the record went somewhere else"
    assert json.loads(written[0].read_text(encoding="utf-8").strip())["case_id"] == "NS-021"


def test_run_aborts_with_exit_4_when_ollama_unreachable(capsys, tmp_cases_csv, tmp_path):
    # Point at a port nothing is listening on — no real daemon involved either way.
    exit_code = cli.main(
        [
            "run",
            "--backend",
            "ollama",
            "--all",
            "--dataset",
            tmp_cases_csv,
            "--runs-dir",
            str(tmp_path / "runs"),
            "--ollama-host",
            "http://localhost:1",
        ]
    )
    out = capsys.readouterr().out

    assert exit_code == 4
    assert "could not reach Ollama" in out
    assert "--backend mock" in out  # points the user at the offline fallback


# --- review / dashboard CLI wiring (coverage gap from the Phase 5-10 review) --


def _seed_run(tmp_path, write_cases_csv, make_case_row, run_id="RUN-1"):
    dataset_path = write_cases_csv(tmp_path / "cases.csv", [_acl_case_row(make_case_row)])
    runs_dir = tmp_path / "runs"
    cli.main(
        ["run", "--backend", "mock", "--case", "NS-021", "--dataset", dataset_path,
         "--runs-dir", str(runs_dir), "--run-id", run_id]
    )
    return dataset_path, runs_dir


def test_review_cli_records_a_verdict_end_to_end(capsys, tmp_path, write_cases_csv, make_case_row, monkeypatch):
    dataset_path, runs_dir = _seed_run(tmp_path, write_cases_csv, make_case_row)
    reviews = tmp_path / "reviews.csv"
    monkeypatch.setattr("builtins.input", lambda *a: "a")

    exit_code = cli.main(
        ["review", "--run", "RUN-1", "--dataset", dataset_path, "--runs-dir", str(runs_dir),
         "--reviews", str(reviews), "--reviewer", "alice"]
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "agreement" in out
    assert "Accepted" in reviews.read_text(encoding="utf-8")


def test_review_cli_exits_1_on_missing_run(capsys, tmp_cases_csv, tmp_path):
    exit_code = cli.main(
        ["review", "--run", "NOPE", "--dataset", tmp_cases_csv, "--runs-dir", str(tmp_path), "--reviewer", "a"]
    )
    assert exit_code == 1
    assert "no run artifact" in capsys.readouterr().out


def test_review_cli_exits_1_without_a_reviewer(capsys, tmp_path, write_cases_csv, make_case_row, monkeypatch):
    dataset_path, runs_dir = _seed_run(tmp_path, write_cases_csv, make_case_row)
    monkeypatch.setattr("builtins.input", lambda *a: "")  # reviewer prompt answered blank

    exit_code = cli.main(
        ["review", "--run", "RUN-1", "--dataset", dataset_path, "--runs-dir", str(runs_dir)]
    )
    assert exit_code == 1
    assert "reviewer name is required" in capsys.readouterr().out


def test_review_cli_exits_1_on_a_corrupt_run_artifact(capsys, tmp_cases_csv, tmp_path):
    (tmp_path / "BAD.jsonl").write_text("{truncated", encoding="utf-8")
    exit_code = cli.main(
        ["review", "--run", "BAD", "--dataset", tmp_cases_csv, "--runs-dir", str(tmp_path), "--reviewer", "a"]
    )
    assert exit_code == 1
    assert "not valid JSON" in capsys.readouterr().out


def test_dashboard_cli_writes_all_three_artifacts(capsys, tmp_path, write_cases_csv, make_case_row):
    dataset_path, runs_dir = _seed_run(tmp_path, write_cases_csv, make_case_row)
    out_dir = tmp_path / "artifacts"

    exit_code = cli.main(
        ["dashboard", "--run", "RUN-1", "--dataset", dataset_path, "--runs-dir", str(runs_dir),
         "--reviews", str(tmp_path / "none.csv"), "--out-dir", str(out_dir)]
    )

    assert exit_code == 0
    assert (out_dir / "dashboard.html").exists()
    assert (out_dir / "dashboard.csv").exists()
    assert (out_dir / "responsible_ai_log.md").exists()
    assert "root cause accuracy" in capsys.readouterr().out


def test_dashboard_cli_exits_1_on_missing_run(capsys, tmp_cases_csv, tmp_path):
    exit_code = cli.main(
        ["dashboard", "--run", "NOPE", "--dataset", tmp_cases_csv, "--runs-dir", str(tmp_path),
         "--out-dir", str(tmp_path)]
    )
    assert exit_code == 1


def test_backend_error_record_names_the_backend(tmp_path, write_cases_csv, make_case_row):
    """Regression: the record read a non-existent .backend attribute and always stored
    "unknown", losing the backend for exactly the records worth investigating [AR-06]."""
    dataset_path = write_cases_csv(tmp_path / "cases.csv", [make_case_row(case_id="NS-001")])
    runs_dir = tmp_path / "runs"
    empty_fixtures = tmp_path / "fx"
    empty_fixtures.mkdir()

    cli.main(
        ["run", "--backend", "mock", "--case", "NS-001", "--dataset", dataset_path,
         "--runs-dir", str(runs_dir), "--fixtures-dir", str(empty_fixtures)]
    )
    record = json.loads((runs_dir / next(runs_dir.glob("*.jsonl")).name).read_text(encoding="utf-8").strip())

    assert record["status"] == "backend_error"
    assert record["backend"] == "mock"

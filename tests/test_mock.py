from netsage.ai.mock import MockClient


def test_mock_client_replays_fixture_by_case_id(tmp_path):
    (tmp_path / "NS-021.json").write_text('{"case_id": "NS-021"}', encoding="utf-8")
    client = MockClient(fixtures_dir=str(tmp_path))

    response = client.complete("system", "## CASE\ncase_id: NS-021\n", temperature=0.0)

    assert response.text == '{"case_id": "NS-021"}'
    assert response.backend == "mock"
    assert response.temperature == 0.0


def test_mock_client_raises_when_case_id_missing_from_prompt(tmp_path):
    client = MockClient(fixtures_dir=str(tmp_path))
    try:
        client.complete("system", "no case id line here", temperature=0.0)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_mock_client_raises_when_fixture_file_missing(tmp_path):
    client = MockClient(fixtures_dir=str(tmp_path))
    try:
        client.complete("system", "case_id: NS-999", temperature=0.0)
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass

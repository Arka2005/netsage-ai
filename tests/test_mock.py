from netsage.ai.mock import MockClient


def test_mock_client_replays_fixture_by_case_id(tmp_path):
    (tmp_path / "NS-021.json").write_text('{"case_id": "NS-021"}', encoding="utf-8")
    client = MockClient(fixtures_dir=str(tmp_path))

    response = client.complete("system", "## CASE\ncase_id: NS-021\n", temperature=0.0)

    assert response.text == '{"case_id": "NS-021"}'
    assert response.backend == "mock"
    assert response.temperature == 0.0


def test_mock_client_uses_the_last_case_id_when_prompt_has_several(tmp_path):
    # Regression: the real diagnose prompt embeds few-shot examples, each with their own
    # "case_id: ..." line — the real case being diagnosed is always the last one.
    (tmp_path / "NS-999.json").write_text('{"case_id": "NS-999"}', encoding="utf-8")
    client = MockClient(fixtures_dir=str(tmp_path))

    prompt = "## EXAMPLE 1\ncase_id: NS-006\n...\n## EXAMPLE 2\ncase_id: NS-021\n...\n## CASE\ncase_id: NS-999\n"
    response = client.complete("system", prompt, temperature=0.0)

    assert response.text == '{"case_id": "NS-999"}'


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

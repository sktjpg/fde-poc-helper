from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.adapters.llm.claude_code_llm import ClaudeCodeLLM
from app.adapters.llm.scripted_llm import call_tool, say
from app.config import Settings
from app.dependencies import get_agent_service, get_llm
from app.domain.errors import LLMError
from app.main import app
from tests.conftest import ServiceFactory


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_chat_page_is_served_and_calls_the_agent_endpoint(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'fetch("/agent/run"' in response.text


def test_chat_page_never_renders_server_content_as_html(client: TestClient) -> None:
    page = client.get("/").text

    assert "innerHTML" not in page


def test_agent_run_returns_structured_result(
    client: TestClient, make_service: ServiceFactory
) -> None:
    script = [call_tool("calculator", operation="add", a=2, b=3), say("It is 5")]
    app.dependency_overrides[get_agent_service] = lambda: make_service(script)

    response = client.post("/agent/run", json={"input": "2 + 3?"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["answer"] == "It is 5"
    assert body["tool_calls"][0]["name"] == "calculator"
    assert body["trace_id"]


def test_agent_run_masks_secrets_in_the_answer(
    client: TestClient, make_service: ServiceFactory
) -> None:
    app.dependency_overrides[get_agent_service] = lambda: make_service(
        [say("key: sk-abcdefghijklmnop1234")]
    )

    response = client.post("/agent/run", json={"input": "hi"})

    assert response.json()["answer"] == "key: [redacted]"


@pytest.mark.parametrize("payload", [{}, {"input": ""}, {"input": "x" * 201}, {"input": "​"}])
def test_agent_run_rejects_invalid_input(
    client: TestClient, make_service: ServiceFactory, payload: dict[str, str]
) -> None:
    app.dependency_overrides[get_agent_service] = lambda: make_service([say("unused")])

    response = client.post("/agent/run", json=payload)

    assert response.status_code == 422
    assert set(response.json()) == {"error"}


def test_tool_arguments_in_the_response_are_masked(
    client: TestClient, make_service: ServiceFactory
) -> None:
    script = [call_tool("lookup", note="my key is sk-abcdefghijklmnop1234"), say("done")]
    app.dependency_overrides[get_agent_service] = lambda: make_service(script)

    response = client.post("/agent/run", json={"input": "hi"})

    assert response.json()["tool_calls"][0]["arguments"] == {"note": "my key is [redacted]"}


def test_claude_code_provider_is_selected_by_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None, llm_provider="claude_code")
    monkeypatch.setattr("app.dependencies.get_settings", lambda: settings)
    get_llm.cache_clear()

    assert isinstance(get_llm(), ClaudeCodeLLM)
    get_llm.cache_clear()


@pytest.mark.parametrize(("retryable", "status_code"), [(True, 503), (False, 502)])
def test_llm_failure_maps_to_a_safe_error(
    client: TestClient, make_service: ServiceFactory, retryable: bool, status_code: int
) -> None:
    error = LLMError("LLM request failed (500)", retryable=retryable)
    app.dependency_overrides[get_agent_service] = lambda: make_service([error])

    response = client.post("/agent/run", json={"input": "hi"})

    assert response.status_code == status_code
    assert response.json() == {"error": "LLM request failed (500)"}


def test_missing_credentials_fail_with_a_clear_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.dependencies.get_settings", lambda: Settings(_env_file=None))
    get_llm.cache_clear()

    response = client.post("/agent/run", json={"input": "hi"})

    assert response.status_code == 502
    assert "credentials are not configured" in response.json()["error"]

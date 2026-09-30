import pytest

from app.prompts.registry import ACTIVE_VERSIONS, get_prompt
from app.prompts.templates import PromptTemplate


def test_every_active_prompt_resolves() -> None:
    for name, version in ACTIVE_VERSIONS.items():
        assert get_prompt(name).id == f"{name}@{version}"


def test_unknown_prompt_or_version_fails_loudly() -> None:
    with pytest.raises(KeyError):
        get_prompt("does_not_exist")
    with pytest.raises(KeyError):
        get_prompt("agent_system", version="v999")


def test_render_refuses_missing_variables() -> None:
    template = PromptTemplate(name="greet", version="v1", text="Hello $name")

    assert template.render(name="Ana") == "Hello Ana"
    with pytest.raises(KeyError):
        template.render()

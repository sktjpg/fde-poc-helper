"""Single lookup point for prompts. Code asks for a name; ACTIVE decides the version."""

from app.prompts.templates import ALL_TEMPLATES, PromptTemplate

# Rolling a prompt forward or back is a one-line change here.
ACTIVE_VERSIONS: dict[str, str] = {"agent_system": "v1"}

_TEMPLATES: dict[tuple[str, str], PromptTemplate] = {
    (template.name, template.version): template for template in ALL_TEMPLATES
}


def get_prompt(name: str, version: str | None = None) -> PromptTemplate:
    resolved = version or ACTIVE_VERSIONS.get(name)
    if resolved is None:
        raise KeyError(f"No active version configured for prompt '{name}'")
    try:
        return _TEMPLATES[(name, resolved)]
    except KeyError:
        raise KeyError(f"Unknown prompt '{name}@{resolved}'") from None

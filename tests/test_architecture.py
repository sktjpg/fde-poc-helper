"""The dependency rule, enforced: inner layers never import outer ones."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
APP = ROOT / "app"
PROVIDER_SDKS = ("anthropic", "openai", "langchain", "langgraph", "mcp", "httpx")
OUTER = ("app.adapters", "app.api", "app.dependencies", "app.main", "fastapi", *PROVIDER_SDKS)

# layer -> modules it must not import
FORBIDDEN: dict[str, tuple[str, ...]] = {
    "domain": (
        *OUTER,
        "app.services",
        "app.agents",
        "app.security",
        "app.prompts",
        "app.observability",
        "app.evaluation",
        "app.config",
        "opentelemetry",
    ),
    "agents": OUTER,
    "services": OUTER,
    "security": OUTER,
    "prompts": OUTER,
    "observability": ("app.adapters", "app.api", "app.dependencies", "app.main", *PROVIDER_SDKS),
}


def imported_modules(path: Path) -> set[str]:
    """Absolute names of everything a file imports, relative imports resolved."""
    package = ".".join(path.relative_to(ROOT).with_suffix("").parts[:-1])
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parent = package.split(".")[: len(package.split(".")) - node.level + 1]
                base = ".".join([*parent, base] if base else parent)
            names.add(base)
            # `from app import adapters` imports the module app.adapters.
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def is_under(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def violations(layer: str) -> list[str]:
    return [
        f"{path.relative_to(ROOT)} imports {module}"
        for path in sorted((APP / layer).rglob("*.py"))
        for module in sorted(imported_modules(path))
        if any(is_under(module, prefix) for prefix in FORBIDDEN[layer])
    ]


@pytest.mark.parametrize("layer", sorted(FORBIDDEN))
def test_layer_respects_the_dependency_rule(layer: str) -> None:
    assert violations(layer) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from app import adapters", "app.adapters"),
        ("from ..adapters.llm import anthropic_llm", "app.adapters.llm"),
        ("from .. import api", "app.api"),
        ("import anthropic.types", "anthropic.types"),
    ],
)
def test_import_resolution_sees_every_import_form(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str, expected: str
) -> None:
    module = tmp_path / "app" / "services" / "sample.py"
    module.parent.mkdir(parents=True)
    module.write_text(source)
    monkeypatch.setattr("tests.test_architecture.ROOT", tmp_path)

    assert expected in imported_modules(module)


def test_prefix_match_respects_module_boundaries() -> None:
    assert is_under("app.api.routes", "app.api")
    assert not is_under("app.apiary", "app.api")

# Repository guide

Agentic backend skeleton: a bounded tool-calling agent behind a FastAPI endpoint, with
guards, tracing, cost tracking and an offline evaluation harness.

## Commands

```bash
make check    # ruff + mypy (strict) + pytest: run before saying anything works
make test     # pytest only
make run      # uvicorn app.main:app --reload  (chat + trace panel at http://localhost:8000,
              # Swagger at /docs; the JSON event log prints in this terminal)
make eval     # golden dataset against the real model (see "Model access")
make up       # observability stack in Docker: Langfuse (LLM traces, :3000) and Grafana with
              # Prometheus, Loki and Tempo (OpenTelemetry metrics, logs, traces, :3001)
make dev      # make up, then the API on this machine exporting all telemetry to that stack
make down     # stop the Docker stack, keep its data (make nuke also deletes the data)
uv add <pkg>  # add a dependency
```

Python 3.12, managed with `uv`.

Docker stack: its parameters (where Docker runs, ports, Langfuse credentials) are in
`docker/<stack>.env`. The default is `docker/local.env`, on this machine. To run it on
another Docker host over SSH, copy `docker/remote.env.example` to `docker/<name>.env` (not
committed) and add `STACK=<name>` to the targets, e.g. `make dev STACK=gmktec`.

Model access: `LLM_PROVIDER=anthropic` (default) calls the API and needs
`ANTHROPIC_API_KEY`. `LLM_PROVIDER=claude_code` runs the local Claude Code CLI headless and
uses this machine's Claude Code login, for development and demos without an API key.
`LLM_PROVIDER=openai_compatible` calls any server with the OpenAI chat-completions API at
`LLM_BASE_URL` (a self-hosted model on Ollama or vLLM, or a hosted gateway); its cost comes
from `LLM_INPUT_PRICE_PER_MTOK` and `LLM_OUTPUT_PRICE_PER_MTOK` when both are set.

Configuration comes from environment variables or `.env` (see `.env.example`). Never read,
print or commit `.env`.

## Layout

```
app/
  main.py            FastAPI entry: router, lifespan, error -> HTTP mapping
  config.py          Settings from the environment
  dependencies.py    Composition root: binds ports to concrete adapters
  domain/            Models, errors, ports. No framework or SDK imports
  services/          Use cases (one each). Orchestrate guards + agent
  agents/            Agent loop and orchestration
    tools/           Typed tools + the registry that validates and executes them
  prompts/           Versioned prompt templates + registry
  security/          input_guard, content_filter, output_filter
  adapters/          Outbound adapters: LLM providers (API, Claude Code CLI, OpenAI-compatible,
                     scripted fake),
                     databases, HTTP clients
  api/               Inbound adapter: routes and request/response schemas
  evaluation/        Golden dataset, offline eval runner, eval_results/ history
  observability/     OpenTelemetry traces, metrics and logs, JSON event log, cost tracker
tests/               Mirrors app/. test_architecture.py enforces the layering
docs/                architecture.md, golden-dataset.md, fde-playbook.md
brief/               Drop the exercise statement here (PDF, markdown, email)
docker/              Parameters of the Docker stack in docker-compose.yml, one file per stack
.claude/, .cursor/   Agent configuration. .cursor/ is generated: edit CLAUDE.md or .claude/,
                     then run `make cursor`
```

## Dependency rule

Dependencies point inwards. `domain` imports nothing from the other layers. `services`,
`agents`, `security` and `prompts` depend on `domain` and on ports, never on `adapters`,
`api`, `fastapi` or a provider SDK. Only `adapters/` imports provider SDKs (OpenTelemetry
is confined to `observability/`), and only `dependencies.py` chooses which adapter
implements a port. `tests/test_architecture.py` fails if this is broken.

## Where things go

| I need to...                         | Put it in                                         |
|--------------------------------------|---------------------------------------------------|
| Add an endpoint                      | `api/routes.py` + `api/schemas.py`, calls a service |
| Add business logic / a use case      | `services/`                                       |
| Add a tool the agent can call        | `agents/tools/<name>.py`, register in `dependencies.py` |
| Call an external API, DB or provider | a port in `domain/ports.py` + an adapter in `adapters/` |
| Change what the model is told        | a new version in `prompts/templates.py`, activate in `prompts/registry.py` |
| Add retrieval                        | port in `domain/ports.py`, implementation in `adapters/`, pipeline in `services/` |
| Cover a new behaviour in evals       | a line in `evaluation/golden_dataset.jsonl`       |

## Conventions

- Immutable data: frozen Pydantic models and frozen dataclasses; build new values instead
  of mutating (`model_copy(update=...)`, `dataclasses.replace`, tuple concatenation).
- Type hints everywhere; `mypy --strict` must pass.
- Domain errors derive from `AppError`. Tool failures return an error `ToolOutput` so the
  model can react; they are not raised through the loop.
- Tests use `ScriptedLLM` instead of a real model. No network in tests.
- No `print` in `app/` outside command-line entry points (use `logging`), no hardcoded
  secrets, no bare `except`.
- Commit messages: `<type>: <description>` (feat, fix, refactor, docs, test, chore).

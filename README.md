# fde-poc-helper

A starting point for building LLM and agent proofs of concept fast, with Claude Code as the
pair programmer, without giving up the things that make a PoC defensible: tests, bounded
agent loops, validated tools, guards, tracing, cost and an evaluation set.

It is aimed at forward-deployed engineering work: a customer or reviewer hands you a problem
(often a PDF), and a few hours later you need something that runs and that you can explain.

It has two independent parts:

1. **Claude Code configuration** (`CLAUDE.md`, `AGENTS.md`, `.claude/`): working rules,
   sub-agents, slash commands and skills for agentic flows, RAG, MCP, LangGraph,
   evaluation, security and observability. Reusable in any repository.
2. **A small backend that already runs** (`app/`, `tests/`): FastAPI, a bounded tool-calling
   agent behind ports and adapters, three guard layers, OpenTelemetry tracing, cost tracking
   and an offline eval harness. Tested, `mypy --strict`, no network needed to run the tests.

Nothing in it is specific to a domain or a customer.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
git clone https://github.com/sktjpg/fde-poc-helper.git && cd fde-poc-helper
uv sync
cp .env.example .env      # choose how to reach a model (see below)
make check                # ruff + mypy + pytest
make run                  # http://localhost:8000/docs
make eval                 # golden dataset against the real model
```

### Model access: API key or your Claude Code login

Set `LLM_PROVIDER` in `.env`:

- `anthropic` (default): the Anthropic API. Needs `ANTHROPIC_API_KEY`.
- `claude_code`: runs the local Claude Code CLI in headless mode (`claude -p`) and uses the
  login already on your machine, so no API key is needed. Each model call starts a
  subprocess (a few seconds), and `cost_usd` is reported as `null` because there is no
  per-token bill. Meant for development and demos; use the API adapter for anything deployed.

`make check` needs neither: the tests run against a scripted model.

```bash
curl -s localhost:8000/agent/run -H 'content-type: application/json' \
  -d '{"input": "What is 1234.5 multiplied by 6789?"}'
```

The response includes the answer, the tool calls made, token usage, cost, the prompt version
and a `trace_id`.

## Working with Claude Code

Open Claude Code in the repository (`claude`). The trigger phrases are in Spanish because
that is how I work; each one is also a slash command and they are easy to rename in
`.claude/commands/` and `CLAUDE.md`.

| You type | What happens |
|---|---|
| `Me piden esto: <requirement>` or `/me-piden` | Analyses the requirement, states the approach in 2-5 sentences, implements the smallest correct solution, adds tests, runs `make check`, and gives you a sentence to explain the decision |
| `/disena <problem>` | Open-ended problem: scopes it and proposes a design before any code |
| `Explícame` or `/explicame` | Explains the code, alternatives, trade-offs and likely questions. Changes nothing |
| `Revisa` or `/revisa` | Independent review: bugs, unbounded loops, injection paths, validation, tests |
| `Simplifica` or `/simplifica` | Removes complexity while preserving behaviour |
| `Production` or `/production` | What is missing for production, ranked by impact. Implements nothing until you choose |
| `/evals <behaviour>` or `/evals run` | Adds golden-dataset cases, or runs the evals and compares with the last run |

If the problem arrives as a document, put it in `brief/` and write
`Me piden esto: lee brief/statement.pdf`.

### What is in `.claude/`

| | |
|---|---|
| `rules/` | Always on: code style, testing, architecture |
| `skills/` | Loaded on demand: `hexagonal-fastapi`, `agent-tools`, `langgraph-agent`, `rag-pipeline`, `mcp-integration`, `golden-dataset`, `llm-security`, `observability` |
| `agents/` | `solution-architect`, `agentic-reviewer`, `eval-engineer`, `production-auditor`, `design-explainer` |
| `commands/` | The commands in the table above |
| `settings.json` | Tests, lint and type checks run without prompting; reading `.env` is denied |

The skills for LangGraph and MCP include small runnable examples that are verified against
the installed versions.

### Using the configuration in another repository

```bash
scripts/install-into.sh /path/to/other-repo
```

Copies `CLAUDE.md` and `.claude/` without overwriting anything, and creates a stub
`AGENTS.md` telling Claude to follow what already exists in that repository.

## The backend

```
app/
  main.py, config.py, dependencies.py   entry point, settings, wiring
  domain/          models, errors, ports (the core: no framework or SDK imports)
  services/        use cases
  agents/          agent loop and tools
  prompts/         versioned prompt templates
  security/        input, content and output guards
  adapters/        external providers (LLM today; databases, APIs, MCP as needed)
  api/             HTTP routes and schemas
  evaluation/      golden dataset, offline eval runner, result history
  observability/   OpenTelemetry tracing, JSON event log, cost tracker
```

What it does, concretely:

- **Bounded agent loop.** A step limit and detection of repeated identical tool calls, so
  it always terminates. Tool failures go back to the model as data; model failures abort.
- **Typed tools.** Arguments are validated against a Pydantic model before the handler
  runs; every call has a timeout.
- **Ports and adapters.** The core depends on an `LLMClient` protocol, not on an SDK. Tests
  run against a scripted fake. A test enforces the dependency rule.
- **Guards.** Input cleaning and limits, size bounds and injection flagging on tool output,
  credential masking on the final answer. These are defence in depth, not the boundary.
- **Tracing.** One trace per run with a span per model call and tool call. Exported to
  Langfuse or any OTLP backend when configured in `.env`; a no-op otherwise.
- **Cost.** Per run, from token usage and a price table.
- **Evaluation.** A golden dataset covering happy path, edge, out-of-scope and adversarial
  cases; the runner scores tool selection and facts, and stores each run.

Deliberately not included until a requirement needs them: retrieval, conversation memory,
persistence, authentication, streaming. The skills describe where each would go.

LangGraph, the MCP SDK, the Langfuse SDK, OpenAI and LangChain provider packages and
`rank-bm25` are installed in an `extras` dependency group so nothing has to be downloaded
mid-session. The backend does not import them.

## Documentation

- [`docs/architecture.md`](docs/architecture.md): request flow, layers, design decisions,
  known limits.
- [`docs/golden-dataset.md`](docs/golden-dataset.md): what a golden dataset is and how to
  build one.
- [`docs/fde-playbook.md`](docs/fde-playbook.md): scoping a problem, choosing deterministic
  versus agentic, and answers to common questions.

## Status

A skeleton, not a framework. The LLM adapters target the Anthropic API and the Claude Code CLI; adding another
provider is one adapter implementing the same port. The unit and loop tests run offline. The
golden dataset runs against a real model; the last result is kept in
`app/evaluation/eval_results/`.

## License

MIT

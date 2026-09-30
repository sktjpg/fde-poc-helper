# Architecture

## Request flow

```
POST /agent/run
  api/routes.py              parse and validate the request
  services/agent_service.py  use case
    security/input_guard       clean and bound the user input
    prompts/registry           resolve the active prompt version
    agents/loop.py             bounded loop
      domain/ports.LLMClient     -> adapters/llm/anthropic_llm.py | claude_code_llm.py
      agents/tools/base.py       validate arguments, timeout, execute
      security/content_filter    bound and flag tool output
      observability/*            spans, event log, cost
    security/output_filter     mask credentials in the answer
  main.py                    domain errors -> HTTP status codes
```

## Layers and the dependency rule

```
        api/  (inbound adapter)          adapters/  (outbound adapters)
              \                               /
               v                             v
        services/   agents/   security/   prompts/        application
                          |
                          v
                       domain/                             core: models, errors, ports
```

Dependencies point inwards. The core defines ports; adapters implement them;
`app/dependencies.py` is the only module that knows which adapter is in use.
`tests/test_architecture.py` fails the build if an inner layer imports an outer one or a
provider SDK.

Why it is worth it here: the LLM is the least stable dependency in the system (models,
SDKs and providers change) and the most expensive to call in tests. Behind a port, the whole
agent runs against `ScriptedLLM` in milliseconds, and changing provider is one adapter.

## The nine layers

| Layer          | Folder            | Responsibility                                           |
|----------------|-------------------|----------------------------------------------------------|
| Entry          | `main.py`, `api/`, `config.py` | HTTP, configuration, error mapping          |
| Core           | `domain/`         | Contracts shared by everything                           |
| Services       | `services/`       | Business logic: one use case each                        |
| Agents         | `agents/`         | LLM-driven orchestration and tools                       |
| Prompts        | `prompts/`        | Versioned templates; the active version is one line      |
| Security       | `security/`       | Input, content and output guards                         |
| Evaluation     | `evaluation/`     | Golden dataset, offline runner, result history           |
| Observability  | `observability/`  | Traces, event log, cost                                  |
| Integrations   | `adapters/`       | Providers, databases, external APIs                      |

Not every exercise needs every layer. Retrieval components, caches, conversation memory and
a frontend are deliberately absent until a requirement asks for them; the skills in
`.claude/skills/` describe where each would go.

## Design decisions

- A plain bounded loop instead of a framework. It is under two hundred lines, fully typed
  and testable. LangGraph is installed for the cases that need explicit state graphs, pausing
  or persistence (`.claude/skills/langgraph-agent/`).
- Termination: a step limit bounds every run, and repeating a call that already succeeded
  with the same arguments ends it early. Failed calls may be retried within the limit. On
  the last step tools are not executed, since nothing would read their results.
- Tool failures are data, not exceptions. Invalid arguments, timeouts and domain failures
  come back to the model as error results so it can correct itself. Only model-call
  failures abort the run.
- Immutable state. Each step produces a new run state; nothing is mutated in place, so a
  run is easy to reason about and safe under concurrency.
- Prompts are versioned and the version is recorded in every result and trace, so a
  behaviour change can be attributed to a prompt change and rolled back.
- OpenTelemetry for tracing, exported only when configured. Langfuse or any OTLP backend is
  a configuration choice.
- Two LLM adapters behind the same port: the Anthropic API for real deployments, and the
  local Claude Code CLI in headless mode for development without an API key. Tests use a
  third, scripted one.
- Cost is reported per run, and is `None` rather than a guess when a model has no known
  price.

## Known limits

- No authentication, rate limiting or persistence.
- Single-turn: no conversation memory.
- No streaming responses.
- The guards are heuristic; real protection is tool permissions and approval steps.
- Evals against the real model are run manually, not in CI.

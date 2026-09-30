# Architecture

Hexagonal (ports and adapters), kept small.

- `domain/` is the core: models, errors, ports (Protocols). It imports only the standard
  library and Pydantic.
- `services/`, `agents/`, `security/`, `prompts/` are application code. They depend on
  `domain` and on ports. They never import `adapters`, `api`, `fastapi` or a provider SDK.
- `adapters/` implements ports with real technology. It is the only place a provider SDK
  is imported. OpenTelemetry is confined to `observability/`.
- `api/` is the inbound adapter: parse the request, call one service, return its result.
  No business logic in route handlers.
- `dependencies.py` is the composition root: the single place that picks adapters.

A new external dependency always arrives as: port in `domain/ports.py`, adapter in
`adapters/`, binding in `dependencies.py`, fake for tests.

`tests/test_architecture.py` enforces these imports. If it fails, move the code; do not
relax the test.

Do not add a layer, port or abstraction until a second use needs it. A small problem gets a
small solution even if that leaves some folders untouched.

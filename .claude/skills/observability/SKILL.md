---
name: observability
description: Tracing, logging and cost tracking for LLM and agent executions in this codebase - OpenTelemetry spans, exporting to Langfuse or any OTLP backend, the JSON event log, per-run cost. Use when adding a new stage, tool or model call that should be traced, when asked how to debug an agent run, when integrating Langfuse or OpenTelemetry, or when asked about cost or latency.
---

# Observability

Goal: for any run, answer "what exactly happened?" from the `trace_id` alone.

## What exists

- `app/observability/tracer.py`
  - `start_span(name, attributes)`: an OpenTelemetry span. A no-op until an exporter is
    configured, so instrumentation is always on and free when tracing is off.
  - `current_trace_id()`: the OpenTelemetry trace id, returned to the caller in
    `AgentResult.trace_id`, so an API response links directly to its trace.
  - `log_event(logger, trace_id, event, **fields)`: one JSON line per event. Values under
    sensitive keys are redacted and credential-shaped strings are masked wherever they
    appear.
  - `configure_logging()`: called at startup so these events reach stderr.
- `app/observability/otel.py`: `configure_tracing(settings)` sets up an OTLP/HTTP exporter
  at startup (FastAPI lifespan) when configured, and flushes on shutdown.
- `app/observability/cost_tracker.py`: price table and `estimate_cost_usd`. Unknown model
  means cost `None`, never a guess.

A run produces this span tree:

```
agent.run                      agent.prompt, agent.status, agent.steps
  llm.call                     gen_ai.response.model, gen_ai.usage.input_tokens/output_tokens
  execute_tool <name>          gen_ai.tool.name, tool.is_error, tool.suspicious
  llm.call
```

Attribute keys are taken from the OpenTelemetry GenAI semantic conventions where one
exists (`gen_ai.usage.*`, `gen_ai.response.model`, `gen_ai.tool.name`), so backends that
understand them can show model and token usage. Coverage is partial: add
`gen_ai.request.model` and the provider name in the adapter if a backend needs them.

## Turning export on

In `.env`, either:

```bash
# Langfuse (takes precedence). It ingests OTLP at <host>/api/public/otel
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com

# or any OpenTelemetry collector / vendor
OTLP_ENDPOINT=http://localhost:4318
OTLP_HEADERS=key=value,key2=value2
```

Nothing else changes. Instrument once with OpenTelemetry, choose the backend by
configuration. If the repository already uses a tracing platform or its SDK, integrate with
that instead of adding a second system.

The `langfuse` SDK is installed in the `extras` group but not used: prefer the OTLP route.
Use the SDK directly only for Langfuse-specific features (scores and user feedback attached
to a trace, prompt management, datasets), behind a port in `adapters/`.

## Adding instrumentation

A new stage (retrieval, reranking, a guard, a sub-agent):

```python
with start_span("retrieval", {"retrieval.k": k}) as span:
    chunks = await retriever.retrieve(query, k)
    span.set_attributes({"retrieval.returned": len(chunks)})
log_event(logger, trace_id, "retrieval", k=k, returned=len(chunks), latency_ms=elapsed)
```

- Span per unit of work that can be slow or fail: model call, tool call, retrieval, external
  request. Not per function.
- Attributes are small scalars: ids, counts, model, status. Not documents or full prompts.
- Never put secrets or personal data in attributes. Tool arguments go through `log_event`,
  which redacts; do not copy them onto spans unfiltered.
- Record failures on the span and re-raise: `span.record_exception(exc)`.
- New model: add its price to `PRICES` in `cost_tracker.py`.

Test with the in-memory exporter, as in `tests/test_observability.py`.

## Feedback and online monitoring

Not implemented; the shape when asked:

- Feedback: `POST /feedback {trace_id, score, comment}` stored against the trace id, so a
  thumbs-down leads straight to the run that caused it.
- Online monitor: sample production runs and compute cheap signals (status other than
  `completed`, tool error rate, steps, cost, latency percentiles, `suspicious` flags).
  Alert on drift; promote interesting failures into the golden dataset as `regression`.

## What to say aloud

"Every run has one trace with a span per model call and tool call, carrying tokens, latency
and status, and the trace id goes back to the caller. It is plain OpenTelemetry, so the
backend, Langfuse or anything OTLP, is configuration."

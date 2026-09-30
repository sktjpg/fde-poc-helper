---
name: observability
description: "Tracing, metrics, logging and cost tracking for LLM and agent executions in this codebase - OpenTelemetry traces, metrics and logs, exporting to Langfuse and any OTLP backend (Grafana LGTM in docker-compose), the JSON event log, per-run cost. Use when adding a new stage, tool or model call that should be traced, when asked how to debug an agent run, when integrating Langfuse or OpenTelemetry, or when asked about cost or latency."
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
  - `span_payload(value)`: redacted, size-capped text for a span's `input.value` and
    `output.value`, which Langfuse and other LLM backends display.
- `app/observability/metrics.py`: counters and histograms through the OpenTelemetry
  metrics API (`agent.runs` by status, `agent.failures`, `agent.run.duration`,
  `agent.run.steps`, `agent.cost`, `gen_ai.client.token.usage`,
  `gen_ai.client.operation.duration`, `agent.tool.calls`, `agent.tool.duration`), recorded
  by the agent loop. No-ops until a MeterProvider is configured.
- `app/observability/otel.py`: `configure_telemetry(settings)` at startup (FastAPI
  lifespan) sets up whatever is configured and flushes it on shutdown: traces to Langfuse
  and to the OTLP endpoint (both when both are set), metrics and logs to the OTLP endpoint.
  `OtelLogHandler` sends the `app` log lines as OpenTelemetry log records linked to the
  active span.
- `app/observability/cost_tracker.py`: price table and `estimate_cost_usd`. Unknown model
  means cost `None`, never a guess.

A run produces this span tree:

```
agent.run                      agent.prompt, agent.status, agent.steps, input/output
  llm.call                     gen_ai.response.model, gen_ai.usage.*_tokens, gen_ai.usage.cost,
                               the new input message and the model output
  execute_tool <name>          gen_ai.tool.name, tool.is_error, tool.suspicious, arguments/result
  llm.call
```

Attribute keys are taken from the OpenTelemetry GenAI semantic conventions where one
exists (`gen_ai.usage.*`, `gen_ai.response.model`, `gen_ai.tool.name`), so backends that
understand them can show model and token usage. Coverage is partial: add
`gen_ai.request.model` and the provider name in the adapter if a backend needs them.

## Turning export on

`make dev` (see AGENTS.md) starts a local stack and sets all of this. By hand, in `.env`:

```bash
# Langfuse: LLM view of the traces. It ingests OTLP at <host>/api/public/otel
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com

# and/or any OpenTelemetry collector or vendor: traces, metrics and logs
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
- Attributes are small scalars: ids, counts, model, status. Payloads (inputs, outputs,
  arguments) only through `span_payload`, which redacts and caps them.
- Metric attributes stay low-cardinality (status, model, tool name, error type): never user
  input, ids or free text. Add a recorder to `metrics.py` for a new stage worth alerting on.
- Record failures on the span and re-raise: `span.record_exception(exc)`.
- New model: add its price to `PRICES` in `cost_tracker.py`.

Test with the in-memory exporters, as in `tests/test_observability.py` and
`tests/test_metrics.py`.

## Dashboards, feedback and online monitoring

The Grafana in the compose stack provisions an "Agent" dashboard
(`docker/grafana/agent-dashboard.json`): runs, failures, p95 duration, tokens, cost, tool
errors, the event log (Loki) and recent traces (Tempo). Not implemented; the shape when
asked:

- Feedback: `POST /feedback {trace_id, score, comment}` stored against the trace id, so a
  thumbs-down leads straight to the run that caused it.
- Online monitor: sample production runs and compute cheap signals (status other than
  `completed`, tool error rate, steps, cost, latency percentiles, `suspicious` flags).
  Alert on drift; promote interesting failures into the golden dataset as `regression`.

## What to say aloud

"Every run has one trace with a span per model call and tool call, carrying tokens, latency
and status, plus metrics for dashboards and alerts and log lines linked to the trace; the
trace id goes back to the caller. It is plain OpenTelemetry, so the backend, Langfuse,
Grafana or a vendor, is configuration."

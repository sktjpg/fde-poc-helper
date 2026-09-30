---
name: agent-tools
description: How to add or change a tool the agent can call, control when the agent uses it, add structured output, or change the agent loop in this codebase. Use for requirements like "add a tool that checks X", "make the agent use it only when Y", "return a structured result", "add retries" or "add an approval step".
---

# Agent tools and loop

## Is it a tool at all?

If the step always happens in the same place, call it from the service in plain code. Make
it a tool only when the model must decide whether and when to call it. "Use X only when Y"
can be read two ways; choose deliberately and say which:

- Y is a fact computable in code (a status field, a threshold): gate deterministically.
  Either the service calls it, or the tool is offered only when the condition holds.
- Y requires interpretation of free text: describe the condition in the tool description
  and let the model decide, then pin the behaviour with golden cases (positive and negative).

## Recipe: add a tool

One file in `app/agents/tools/`, copying `calculator.py`:

```python
class InvoiceStatusArgs(BaseModel):
    invoice_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class InvoiceStatus(BaseModel):
    invoice_id: str
    status: Literal["draft", "open", "paid", "overdue"]
    due_date: date | None


def make_invoice_status_tool(gateway: InvoiceGateway) -> Tool[InvoiceStatusArgs]:
    async def handler(args: InvoiceStatusArgs) -> InvoiceStatus:
        return await gateway.status_of(args.invoice_id)

    return Tool(
        name="get_invoice_status",
        description=(
            "Current status of one invoice, by id. Use only when the user asks about a "
            "specific invoice. Do not use for general billing or pricing questions."
        ),
        args_model=InvoiceStatusArgs,
        handler=handler,
    )
```

Then register it in `get_tools` in `app/dependencies.py`.

Rules:

- Arguments are a Pydantic model with tight constraints (lengths, patterns, enums, ranges).
  The registry validates before the handler runs, so the handler can trust its input.
- The return type is a Pydantic model: that is the output contract the model reads.
- Tools that do I/O take their port through a factory (as above). No SDK import here.
- Expected failures raise `ToolError("message safe for the model")`. The registry turns
  them, timeouts, invalid arguments and unknown tools into error outputs the model can react
  to. Unexpected exceptions are logged and replaced by a generic message.
- The description states when to use the tool and when not to. It is the main lever on
  tool selection, more than the system prompt.
- Tools with side effects need an approval step (see `langgraph-agent`) and idempotency.

Tests for a new tool (`tests/test_tools.py` style): valid call, invalid arguments, domain
failure, and for I/O tools timeout and malformed upstream response. Then a loop test with
`ScriptedLLM`, and golden cases: one where the tool must be used, one where it must not.

## What the loop already guarantees (`app/agents/loop.py`)

- `max_steps` bounds the number of model calls: status `max_steps`. Tools requested on the
  last step are not executed.
- A call that already succeeded, repeated with the same arguments: status `stalled`. Failed
  calls may be retried.
- Each tool call has a timeout (`ToolRegistry`).
- Tool calls in one step run concurrently and their results go back in one message.
- Tool output passes through `filter_untrusted` (size bound, injection flag).

Keep these when changing the loop. Any new cycle needs its own bound.

## Structured final output

When downstream code consumes the answer, do not parse prose. Define the result model,
ask the model for JSON matching its schema, validate, and retry a bounded number of times
with the validation error appended:

```python
class InvestigationResult(BaseModel):
    root_cause: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[str]
    recommended_action: str


try:
    result = InvestigationResult.model_validate_json(answer_text)
except ValidationError as exc:
    ...  # one bounded retry with exc.errors() in the prompt, then a domain error
```

With the Anthropic SDK the constrained route is `client.messages.parse(...,
output_format=Model)` in the adapter, which returns an already validated object. Keep that
inside `adapters/`; expose it through the port.

## Retries

Retry only what is retryable (`LLMError.retryable`, timeouts, 429, 5xx), with a small fixed
maximum and backoff, and never a call with side effects unless it is idempotent. The
Anthropic client already retries twice by default; do not stack blind retries on top.

## What to say aloud

"The tool is typed and validated before it runs, failures come back to the model as data so
it can recover, and the loop is bounded by a step limit and duplicate-call detection."

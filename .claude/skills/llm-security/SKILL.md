---
name: llm-security
description: Security for LLM and agent features in this codebase - prompt injection, the three guard layers (input, content, output), tool permissions, human approval for consequential actions, secrets and safe logging. Use when adding tools with side effects, handling untrusted content (documents, web pages, emails, tool or RAG results), exposing a new endpoint, or when asked about prompt injection or guardrails.
---

# LLM security

## Threat model in one paragraph

The model cannot reliably tell instructions from data. Anything it reads (user text, a tool
result, a retrieved chunk, an email, a web page) can contain instructions, and some of them
will be followed. So the question is never "will the model resist?" but "what is the worst
thing this agent can do if it is fully steered by an attacker?". Security comes from
limiting that, in code.

## Controls, strongest first

1. Least privilege on tools. The agent can only do what its tools allow. Read-only by
   default; narrow arguments (ids validated by pattern, enums, ranges); scope every call to
   the authenticated user in the handler, never from a model-supplied user id.
2. Deterministic gates on consequential actions. Sending, paying, deleting, changing
   records: the model proposes, code checks policy, a human approves (see
   `langgraph-agent/example_hitl.py`). The approval shows the actual action and arguments.
3. Validation between steps. If a tool result feeds another tool call, validate it against a
   schema or an allowlist first. URLs against an allowlist of hosts. No model-written SQL:
   expose parameterised queries as tools instead.
4. Separation. System instructions, user input, retrieved data and tool output stay in
   separate channels or clearly delimited blocks. Never concatenate untrusted text into the
   system prompt.
5. The three guards in `app/security/` (below). Heuristic, cheap, defence in depth.

Be precise about this when asked: pattern matching for "ignore previous instructions" is
a tripwire for tracing and alerting, not a defence. Layers 1 to 3 are the defence.

## The three guards

| Guard | File | Does | Wired in |
|---|---|---|---|
| Input | `input_guard.py` | strips control/invisible characters, rejects empty or oversized input | `AgentService.answer` |
| Content | `content_filter.py` | bounds size of untrusted content, flags injection patterns | agent loop, on every tool output |
| Output | `output_filter.py` | masks credential-shaped strings in the final answer | `AgentService.answer` |

Extending them: a new untrusted source (retrieved chunks, fetched pages) goes through
`filter_untrusted` before entering the context, and the `suspicious` flag is traced. New
output rules (PII, internal identifiers) go in `output_filter.py` with a test.

## Secrets and logs

- Secrets only from the environment (`app/config.py`, `SecretStr`). Never in code, prompts,
  tool descriptions, test fixtures or error messages.
- `.env` is denied to the coding agent in `.claude/settings.json`; keep it that way.
- Logs and traces go through `log_event`, which redacts sensitive keys. Do not log full
  prompts or tool results that may contain personal data without a reason.
- API errors return a safe message; stack traces stay in server logs.

## API surface

Validate length and shape at the edge, authenticate before doing work, rate limit per
caller, bound cost per request (`agent_max_steps`, `llm_max_tokens`, tool timeouts). An
unauthenticated endpoint that triggers LLM calls is a cost and abuse vector.

## Tests to add with a risky change

- A tool result containing an instruction does not cause a forbidden tool call (loop test
  with `ScriptedLLM`, and an `adversarial` golden case against the real model).
- Invalid or out-of-scope tool arguments are rejected before execution.
- The consequential action does not run without approval.

## What to say aloud

"I assume injection will sometimes succeed, so the control is what the agent is able to do:
least-privilege tools, validated arguments, and human approval on anything irreversible.
The content filters are a tripwire on top, not the boundary."

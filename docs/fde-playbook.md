# Forward-deployed engineer playbook

What the role is judged on: turning an ambiguous customer problem into something that
works in their environment, with sound judgement about what to build, what not to build
and what could go wrong. Code quality matters; judgement matters more.

## The first five minutes of any exercise

Say these aloud before writing code. It shows scoping, which is most of the job.

1. Restate the problem in one sentence, in the user's terms.
2. Who uses the output, and what do they do with it?
3. What does success look like? Name a measurable outcome.
4. What are the inputs and where do they come from? How dirty are they?
5. What must never happen? (wrong refund, leaked data, action on the wrong record)
6. State your assumptions and proceed: "I'll assume X and Y; tell me if that's wrong."

Useful clarifying questions:

- "Is the workflow fixed, or does it vary per request?" (deterministic vs agentic)
- "Does this action have side effects, or is it read-only?" (approval step)
- "What happens today when this data is missing or the upstream is down?"
- "What volume and latency should I design for?"
- "Is there existing tracing or an eval set I should integrate with?"

## Deterministic or agentic

| Signal                                             | Choose                             |
|----------------------------------------------------|------------------------------------|
| Steps are known in advance                         | Plain code                         |
| Input is free text that must be interpreted        | One LLM call with structured output |
| A few known branches                               | LLM classifies, code routes        |
| The next step depends on what the last one found   | Agent loop with tools              |
| Must pause for a person, or resume later           | State graph with checkpointing     |

Default to the row highest in the table that solves the problem. Each step down adds cost,
latency, non-determinism and things to evaluate.

## Things to say, and mean

Scoping

- "Before I code: the workflow here is known in advance, so I'll keep it deterministic and
  use the model only to interpret the free-text part."
- "I'll build the thinnest end-to-end slice first, then harden it."

Agent design

- "The loop is bounded two ways: a step limit and detection of repeated identical tool
  calls, so it cannot run away."
- "Tools are typed and validated before they run. A tool failure goes back to the model as
  data so it can recover; only a model failure aborts the run."
- "I want structured output validated against a schema, not prose I have to parse."

Reliability and safety

- "I treat everything the model reads as untrusted. The real control is what the tools are
  allowed to do, plus human approval on anything irreversible."
- "Every external call has a timeout, and I only retry what is idempotent."

Evaluation

- "I wouldn't judge this by reading a few outputs. I'd add golden cases: one where the new
  behaviour must happen and one where it must not."
- "Unit tests use a scripted model and prove the code; the golden set uses the real model
  and proves the behaviour."

Observability and cost

- "Each run has a trace id with a span per model and tool call, so I can reconstruct exactly
  what happened."
- "I'd use a smaller model for routing and extraction and keep the larger one for the
  reasoning step. I'd measure before and after on the golden set."

Trade-offs

- "The simplest thing that works here is X. I'd move to Y when Z becomes true."
- "This is the part I'd change first for production: ..."

## When you do not know

- Say what you know, what you would check, and how. "I haven't used that API; I'd read its
  schema and failure modes first and wrap it behind a port so I can fake it in tests."
- Never bluff about an API. Look at the code or the docs.

## Common follow-ups, short answers

- "What if the model returns garbage?" Validate against the schema, retry once with the
  validation error, then fail explicitly with a safe message.
- "What if the tool API is down?" Timeout, error result to the model, it explains or the
  run fails cleanly; no silent wrong answer.
- "How do you stop prompt injection?" You limit blast radius: least-privilege tools,
  validated arguments, approval for consequential actions, separation of instructions from
  data. Filters are a tripwire.
- "How would this scale?" The service is stateless; bound concurrency to upstream limits;
  move long runs to background jobs; cache deterministic lookups; route cheap tasks to
  cheaper models.
- "How do you know a prompt change is safe?" Prompts are versioned; run the golden set
  before and after; keep the previous version one line away for rollback.
- "Why not LangChain or LangGraph for this?" For one tool loop, a couple of hundred lines of
  typed code is easier to read, test and debug. I'd adopt a graph framework when I need branching
  state, pausing for approval or persistence.
- "What would you do with more time?" Name three concrete things in priority order, not a
  wish list.

## Working with the AI assistant in front of other people

- Narrate intent before each request: what you are about to ask for and why.
- Read the diff before accepting it. Say what you are checking.
- Ask for small changes. If the assistant proposes something larger than needed, cut it.
- Run the tests yourself and read the output aloud.
- Own the decisions: "I asked for a port here because...", not "it generated...".

---
name: langgraph-agent
description: When and how to use LangGraph in this codebase - explicit state graphs, branching, cycles, checkpointing and human-in-the-loop approval. Use when a requirement mentions LangGraph, multi-step workflows with branches, pausing for human approval, resumable runs, or when deciding between the plain agent loop and a graph.
---

# LangGraph: use it or not

LangGraph is installed (`langgraph`, `langchain-anthropic`, `langchain-openai` in the
`extras` group) but the skeleton does not depend on it. The plain loop in
`app/agents/loop.py` is under 200 lines and covers a single tool-calling agent.

## Decision

Stay with the plain loop when: one agent, one cycle (model, tools, model), no pause or
resume. It is easier to read, test and explain.

Move to LangGraph when at least one of these is real:

- Several distinct stages with branching (classify, then route to different handlers).
- Human approval in the middle of a run, resumed later (interrupt + checkpointer).
- Runs that must survive a restart or be resumed (persistent checkpointer).
- Per-node retries, or a workflow that stakeholders need to see as a graph.
- The requirement or the existing codebase calls for it.

Say the reason: "I'm using LangGraph here because the run has to pause for approval and
resume, which needs persisted state. For a single tool loop I would keep plain code."

## Reference implementations (verified, runnable)

- `example_graph.py`: the current agent loop as a `StateGraph`, reusing our `LLMClient`
  port and `ToolRegistry`. Shows typed state, a reducer, a conditional edge and the
  termination bound.
- `example_hitl.py`: propose, `interrupt()` for approval, resume with `Command(resume=...)`.

Run either with `uv run python .claude/skills/langgraph-agent/<file>`.

## Adopting it in the app

1. Add the dependency to the main group: `uv add langgraph`.
2. Put the graph in `app/agents/graph.py`, built from ports like the example. Keep
   LangChain model classes out: our `LLMClient` port already abstracts the provider.
3. Keep the same guarantees as the loop: a step counter in state checked in the routing
   function, tool timeouts from `ToolRegistry`, `filter_untrusted` on tool output.
   `recursion_limit` in the run config is a second safety net, not the primary bound.
4. Return the same `AgentResult` from the service so the API and the evals do not change.
5. The architecture test allows `langgraph` only if you remove it from `SDKS` for the
   `agents` layer in `tests/test_architecture.py`. Do that explicitly.

## Essentials

- State is a `TypedDict`; a field annotated with a reducer (`Annotated[tuple[...],
  operator.add]`) is appended to, others are overwritten. Nodes return only what changed.
- `add_conditional_edges(node, route_fn)`: `route_fn` returns the next node name or
  `"__end__"`. Annotate its return type with `Literal[...]` so the graph knows the targets.
- `interrupt(value)` pauses and returns the resume value when the graph is invoked again
  with `Command(resume=...)` on the same `thread_id`. It requires a checkpointer.
- The node containing `interrupt` re-runs from its start on resume: do nothing with side
  effects before the `interrupt` call in that node.
- `InMemorySaver` for tests and demos; a database-backed saver for anything real.
- Test graphs the same way as the loop: `ScriptedLLM`, assert on final state and on the
  sequence of nodes.

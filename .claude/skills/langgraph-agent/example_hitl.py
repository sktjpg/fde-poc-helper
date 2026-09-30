"""Reference: human-in-the-loop approval with LangGraph interrupt + checkpointer.

propose action -> pause for approval -> execute or skip. Verified against langgraph 1.2:

    uv run python .claude/skills/langgraph-agent/example_hitl.py
"""

from typing import Any, Literal, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class ApprovalState(TypedDict):
    proposed_action: str
    outcome: str


def propose(state: ApprovalState) -> dict[str, Any]:
    return {"proposed_action": "send refund of 120 EUR"}


def approval(state: ApprovalState) -> Command[Literal["execute", "__end__"]]:
    # Pauses the graph here. The value is what the caller sees; the resume value comes back.
    approved = interrupt({"action": state["proposed_action"], "question": "Approve?"})
    if approved:
        return Command(goto="execute")
    return Command(goto="__end__", update={"outcome": "rejected by human"})


def execute(state: ApprovalState) -> dict[str, Any]:
    return {"outcome": f"executed: {state['proposed_action']}"}


def build_graph() -> Any:
    graph = StateGraph(ApprovalState)
    graph.add_node("propose", propose)
    graph.add_node("approval", approval)
    graph.add_node("execute", execute)
    graph.add_edge(START, "propose")
    graph.add_edge("propose", "approval")
    graph.add_edge("execute", END)
    # A checkpointer is required: the paused state must be stored to be resumed later.
    return graph.compile(checkpointer=InMemorySaver())


def main() -> None:
    graph = build_graph()
    config = {"configurable": {"thread_id": "request-1"}}

    paused = graph.invoke({"proposed_action": "", "outcome": ""}, config)
    print("waiting for:", paused["__interrupt__"][0].value)

    final = graph.invoke(Command(resume=True), config)
    print("outcome:", final["outcome"])


if __name__ == "__main__":
    main()

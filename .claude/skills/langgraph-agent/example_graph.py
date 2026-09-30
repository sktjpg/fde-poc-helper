"""Reference: the agent loop from app/agents/loop.py expressed as a LangGraph graph.

Reuses the project's own port (LLMClient) and ToolRegistry, so no LangChain model classes
are needed. Verified against langgraph 1.2:

    uv run python .claude/skills/langgraph-agent/example_graph.py
"""

import asyncio
import operator
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.adapters.llm.scripted_llm import ScriptedLLM, call_tool, say
from app.agents.tools.base import ToolRegistry
from app.agents.tools.calculator import calculator
from app.domain.models import Message
from app.domain.ports import LLMClient


class AgentState(TypedDict):
    # Reducer: each node returns only the new messages and LangGraph appends them.
    messages: Annotated[tuple[Message, ...], operator.add]
    steps: int


def build_graph(
    llm: LLMClient, tools: ToolRegistry, *, system_prompt: str, max_steps: int
) -> CompiledStateGraph[AgentState, Any, Any, Any]:
    async def call_model(state: AgentState) -> dict[str, Any]:
        response = await llm.complete(
            system=system_prompt, messages=state["messages"], tools=tools.specs()
        )
        return {"messages": (response.message,), "steps": state["steps"] + 1}

    async def run_tools(state: AgentState) -> dict[str, Any]:
        calls = state["messages"][-1].tool_calls
        outputs = await asyncio.gather(*(tools.execute(call) for call in calls))
        return {"messages": (Message(role="tool", tool_outputs=tuple(outputs)),)}

    def route(state: AgentState) -> Literal["tools", "__end__"]:
        wants_tools = bool(state["messages"][-1].tool_calls)
        # Termination guarantee: stop at max_steps even if the model keeps asking for tools.
        return "tools" if wants_tools and state["steps"] < max_steps else "__end__"

    graph = StateGraph(AgentState)
    graph.add_node("model", call_model)
    graph.add_node("tools", run_tools)
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", route)
    graph.add_edge("tools", "model")
    return graph.compile()


async def main() -> None:
    llm = ScriptedLLM([call_tool("calculator", operation="add", a=2, b=3), say("It is 5")])
    tools = ToolRegistry([calculator], timeout_seconds=1.0)
    graph = build_graph(llm, tools, system_prompt="Be precise.", max_steps=4)

    final = await graph.ainvoke({"messages": (Message(role="user", text="2 + 3?"),), "steps": 0})

    print([message.role for message in final["messages"]], "->", final["messages"][-1].text)


if __name__ == "__main__":
    asyncio.run(main())

"""Bounded tool-calling agent loop.

reason -> select tools -> execute -> feed results back -> repeat until the model answers.
Termination is guaranteed by max_steps; repeating a call that already succeeded stops early.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, replace

from app.agents.tools.base import ToolRegistry
from app.domain.errors import AppError
from app.domain.models import (
    AgentResult,
    AgentStatus,
    LLMResponse,
    Message,
    ToolCall,
    ToolCallRecord,
    ToolOutput,
    Usage,
)
from app.domain.ports import LLMClient
from app.observability.cost_tracker import estimate_cost_usd
from app.observability.tracer import SpanAttributes, current_trace_id, log_event, start_span
from app.prompts.templates import PromptTemplate
from app.security.content_filter import filter_untrusted

logger = logging.getLogger(__name__)

STALLED_ANSWER = "Stopped: the agent kept repeating the same tool calls."
MAX_STEPS_ANSWER = "Stopped: step limit reached before a final answer."


@dataclass(frozen=True)
class _Run:
    """Everything known about one execution. Replaced, never mutated, at each step."""

    trace_id: str
    prompt_id: str
    messages: tuple[Message, ...]
    records: tuple[ToolCallRecord, ...] = ()
    seen_calls: frozenset[str] = frozenset()
    usage: Usage = Usage()
    call_costs: tuple[float | None, ...] = ()

    def result(self, status: AgentStatus, answer: str, steps: int) -> AgentResult:
        # One unpriced call makes the total unknown: report None rather than a partial sum.
        known = [cost for cost in self.call_costs if cost is not None]
        return AgentResult(
            trace_id=self.trace_id,
            status=status,
            answer=answer,
            steps=steps,
            prompt_version=self.prompt_id,
            tool_calls=self.records,
            usage=self.usage,
            cost_usd=round(sum(known), 6) if len(known) == len(self.call_costs) else None,
        )


async def run_agent(
    user_input: str,
    *,
    llm: LLMClient,
    tools: ToolRegistry,
    prompt: PromptTemplate,
    max_steps: int,
) -> AgentResult:
    with start_span("agent.run", {"agent.prompt": prompt.id}) as span:
        run = _Run(
            trace_id=current_trace_id(),
            prompt_id=prompt.id,
            messages=(Message(role="user", text=user_input),),
        )
        try:
            result = await _loop(run, llm, tools, prompt.render(), max_steps)
        except AppError as exc:
            # The failure must be findable by trace id, not only the successes.
            log_event(
                logger, run.trace_id, "agent_failed", error=type(exc).__name__, detail=str(exc)
            )
            raise
        span.set_attributes({"agent.status": result.status, "agent.steps": result.steps})
        log_event(
            logger,
            result.trace_id,
            "agent_finished",
            status=result.status,
            steps=result.steps,
            cost_usd=result.cost_usd,
        )
        return result


async def _loop(
    run: _Run, llm: LLMClient, tools: ToolRegistry, system_prompt: str, max_steps: int
) -> AgentResult:
    for step in range(1, max_steps + 1):
        response = await _call_llm(run, llm, tools, system_prompt, step)
        run = replace(
            run,
            messages=(*run.messages, response.message),
            usage=run.usage + response.usage,
            call_costs=(*run.call_costs, estimate_cost_usd(response.model, response.usage)),
        )
        calls = response.message.tool_calls
        if not calls:
            return run.result("completed", response.message.text, step)

        if frozenset(_signature(call) for call in calls) <= run.seen_calls:
            # Calls that already succeeded, with the same arguments: nothing new can come back.
            return run.result("stalled", STALLED_ANSWER, step)
        if step == max_steps:
            # No model call is left to read the results, so do not run the tools at all.
            break

        executed = await asyncio.gather(
            *(_execute(tools, call, step, run.trace_id) for call in calls)
        )
        outputs = tuple(output for output, _ in executed)
        # Failed calls are not remembered: retrying a timeout is legitimate, and max_steps
        # still bounds it.
        succeeded = frozenset(
            _signature(call)
            for call, (output, _) in zip(calls, executed, strict=True)
            if not output.is_error
        )
        run = replace(
            run,
            messages=(*run.messages, Message(role="tool", tool_outputs=outputs)),
            records=(*run.records, *(record for _, record in executed)),
            seen_calls=run.seen_calls | succeeded,
        )

    return run.result("max_steps", MAX_STEPS_ANSWER, max_steps)


async def _call_llm(
    run: _Run, llm: LLMClient, tools: ToolRegistry, system_prompt: str, step: int
) -> LLMResponse:
    started = time.perf_counter()
    with start_span("llm.call", {"gen_ai.operation.name": "chat", "agent.step": step}) as span:
        response = await llm.complete(
            system=system_prompt, messages=run.messages, tools=tools.specs()
        )
        span.set_attributes(
            {
                "gen_ai.response.model": response.model,
                "gen_ai.usage.input_tokens": response.usage.input_tokens,
                "gen_ai.usage.output_tokens": response.usage.output_tokens,
            }
        )
    log_event(
        logger,
        run.trace_id,
        "llm_call",
        step=step,
        model=response.model,
        prompt=run.prompt_id,
        latency_ms=_elapsed_ms(started),
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        tool_calls=[call.name for call in response.message.tool_calls],
    )
    return response


async def _execute(
    tools: ToolRegistry, call: ToolCall, step: int, trace_id: str
) -> tuple[ToolOutput, ToolCallRecord]:
    started = time.perf_counter()
    attributes: SpanAttributes = {
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": call.name,
    }
    with start_span(f"execute_tool {call.name}", attributes) as span:
        raw = await tools.execute(call)
        # Tool output is untrusted data: bound its size and flag injection attempts.
        filtered = filter_untrusted(raw.content)
        span.set_attributes({"tool.is_error": raw.is_error, "tool.suspicious": filtered.suspicious})
    record = ToolCallRecord(
        step=step,
        name=call.name,
        arguments=call.arguments,
        is_error=raw.is_error,
        latency_ms=_elapsed_ms(started),
    )
    log_event(
        logger,
        trace_id,
        "tool_call",
        **record.model_dump(),
        suspicious=filtered.suspicious,
        truncated=filtered.truncated,
    )
    return raw.model_copy(update={"content": filtered.text}), record


def _signature(call: ToolCall) -> str:
    return f"{call.name}:{json.dumps(call.arguments, sort_keys=True, default=str)}"


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)

"""Offline eval: run the golden dataset through the real agent and score behaviour.

    uv run python -m app.evaluation.offline_eval     # real model, needs ANTHROPIC_API_KEY

Scores what the agent did (tools used, facts present or absent, steps), not its wording.
Each run is saved under eval_results/ so quality can be compared across changes.
"""

import asyncio
import json
import re
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.domain.errors import AppError
from app.domain.models import AgentResult
from app.services.agent_service import AgentService

EVALUATION_DIR = Path(__file__).parent
GOLDEN_PATH = EVALUATION_DIR / "golden_dataset.jsonl"
RESULTS_DIR = EVALUATION_DIR / "eval_results"

NUMBER = re.compile(r"-?\d+(\.\d+)?")

Category = Literal["happy_path", "edge_case", "out_of_scope", "adversarial", "regression"]


class EvalCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    category: Category
    input: str
    expected_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    expected_facts: tuple[str, ...] = ()
    forbidden_facts: tuple[str, ...] = ()
    max_steps: int | None = None
    notes: str = ""


class CaseResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    category: Category
    passed: bool
    tools_correct: bool
    facts_correct: bool
    steps: int
    latency_ms: float
    total_tokens: int
    cost_usd: float | None
    failures: tuple[str, ...] = ()


class EvalReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    results: tuple[CaseResult, ...]

    @property
    def task_success_rate(self) -> float:
        return _rate([result.passed for result in self.results])

    @property
    def tool_selection_accuracy(self) -> float:
        return _rate([result.tools_correct for result in self.results])

    def summary(self) -> dict[str, float | int | None]:
        return {
            "cases": len(self.results),
            "task_success_rate": round(self.task_success_rate, 3),
            "tool_selection_accuracy": round(self.tool_selection_accuracy, 3),
            "avg_steps": round(_mean([result.steps for result in self.results]), 2),
            "avg_latency_ms": round(_mean([result.latency_ms for result in self.results]), 1),
            "total_tokens": sum(result.total_tokens for result in self.results),
            "total_cost_usd": self.total_cost_usd,
        }

    @property
    def total_cost_usd(self) -> float | None:
        costs = [result.cost_usd for result in self.results]
        known = [cost for cost in costs if cost is not None]
        return round(sum(known), 6) if costs and len(known) == len(costs) else None


def load_cases(path: Path = GOLDEN_PATH) -> list[EvalCase]:
    lines = [line for line in path.read_text().splitlines() if line.strip()]
    cases = [EvalCase.model_validate_json(line) for line in lines]
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Golden dataset has duplicate case ids")
    return cases


def score(case: EvalCase, result: AgentResult, latency_ms: float) -> CaseResult:
    used = {record.name for record in result.tool_calls}
    answer = _normalise(result.answer)

    missing_tools = set(case.expected_tools) - used
    banned_tools = set(case.forbidden_tools) & used
    missing_facts = [fact for fact in case.expected_facts if not _contains(answer, fact)]
    banned_facts = [fact for fact in case.forbidden_facts if _contains(answer, fact)]
    too_many_steps = case.max_steps is not None and result.steps > case.max_steps

    failures = (
        *([f"agent status: {result.status}"] if result.status != "completed" else []),
        *(["empty answer"] if not answer.strip() else []),
        *(f"expected tool not used: {name}" for name in sorted(missing_tools)),
        *(f"forbidden tool used: {name}" for name in sorted(banned_tools)),
        *(f"expected fact missing: {fact}" for fact in missing_facts),
        *(f"forbidden fact present: {fact}" for fact in banned_facts),
        *([f"took {result.steps} steps, limit {case.max_steps}"] if too_many_steps else []),
    )
    return CaseResult(
        case_id=case.id,
        category=case.category,
        passed=not failures,
        tools_correct=not missing_tools and not banned_tools,
        facts_correct=not missing_facts and not banned_facts,
        steps=result.steps,
        latency_ms=latency_ms,
        total_tokens=result.usage.input_tokens + result.usage.output_tokens,
        cost_usd=result.cost_usd,
        failures=failures,
    )


async def run_case(case: EvalCase, service: AgentService) -> CaseResult:
    started = time.perf_counter()
    try:
        result = await service.answer(case.input)
    except AppError as exc:
        return CaseResult(
            case_id=case.id,
            category=case.category,
            passed=False,
            tools_correct=False,
            facts_correct=False,
            steps=0,
            latency_ms=_elapsed_ms(started),
            total_tokens=0,
            cost_usd=None,
            failures=(f"{type(exc).__name__}: {exc}",),
        )
    return score(case, result, _elapsed_ms(started))


async def run_evals(cases: Sequence[EvalCase], service: AgentService) -> EvalReport:
    # Sequential on purpose: stays inside provider rate limits and keeps output readable.
    results = [await run_case(case, service) for case in cases]
    return EvalReport(results=tuple(results))


def save_report(report: EvalReport, directory: Path = RESULTS_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    payload = {"summary": report.summary(), "results": report.model_dump()["results"]}
    path.write_text(json.dumps(payload, indent=2))
    return path


def _normalise(text: str) -> str:
    # Case and thousands separators must not decide whether a fact counts as present.
    return text.lower().replace(",", "")


def _contains(answer: str, fact: str) -> bool:
    """Substring match, except numbers, which must match as whole numbers (126 is not in 1260)."""
    needle = _normalise(fact)
    if NUMBER.fullmatch(needle):
        return re.search(rf"(?<![\d.]){re.escape(needle)}(?!\.?\d)", answer) is not None
    return needle in answer


def _rate(flags: Sequence[bool]) -> float:
    return sum(flags) / len(flags) if flags else 0.0


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


async def main() -> int:
    from app.config import get_settings
    from app.dependencies import get_agent_service, get_llm, get_tools

    settings = get_settings()
    service = get_agent_service(get_llm(), get_tools(settings), settings)
    report = await run_evals(load_cases(), service)
    for result in report.results:
        status = "PASS" if result.passed else "FAIL"
        print(f"{status}  {result.case_id}  {'; '.join(result.failures)}")
    print(json.dumps(report.summary(), indent=2))
    print(f"saved: {save_report(report)}")
    return 0 if report.task_success_rate == 1.0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

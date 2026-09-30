from pathlib import Path

import pytest

from app.adapters.llm.scripted_llm import call_tool, say
from app.domain.errors import LLMError
from app.evaluation.offline_eval import EvalCase, load_cases, run_case, run_evals, save_report
from tests.conftest import ServiceFactory

MULTIPLY = EvalCase(
    id="multiply",
    category="happy_path",
    input="6 times 7?",
    expected_tools=("calculator",),
    expected_facts=("42",),
)
MULTIPLY_SCRIPT = [call_tool("calculator", operation="multiply", a=6, b=7), say("It is 42.")]


def test_golden_dataset_is_valid_and_covers_every_risk_category() -> None:
    cases = load_cases()

    assert {case.category for case in cases} >= {
        "happy_path",
        "edge_case",
        "out_of_scope",
        "adversarial",
    }


def test_duplicate_case_ids_are_rejected(tmp_path: Path) -> None:
    line = MULTIPLY.model_dump_json()
    path = tmp_path / "golden.jsonl"
    path.write_text(f"{line}\n{line}\n")

    with pytest.raises(ValueError, match="duplicate"):
        load_cases(path)


async def test_case_passes_when_tools_and_facts_match(make_service: ServiceFactory) -> None:
    result = await run_case(MULTIPLY, make_service(MULTIPLY_SCRIPT))

    assert result.passed
    assert result.failures == ()


async def test_case_fails_when_the_expected_tool_is_skipped(make_service: ServiceFactory) -> None:
    result = await run_case(MULTIPLY, make_service([say("It is 42.")]))

    assert not result.passed
    assert not result.tools_correct
    assert result.facts_correct
    assert result.failures == ("expected tool not used: calculator",)


async def test_case_fails_on_forbidden_tool_and_forbidden_fact(
    make_service: ServiceFactory,
) -> None:
    case = EvalCase(
        id="no-tool",
        category="out_of_scope",
        input="say hi",
        forbidden_tools=("calculator",),
        forbidden_facts=("42",),
    )

    result = await run_case(case, make_service(MULTIPLY_SCRIPT))

    assert result.failures == ("forbidden tool used: calculator", "forbidden fact present: 42")


async def test_case_fails_when_it_takes_too_many_steps(make_service: ServiceFactory) -> None:
    case = MULTIPLY.model_copy(update={"max_steps": 1})

    result = await run_case(case, make_service(MULTIPLY_SCRIPT))

    assert result.failures == ("took 2 steps, limit 1",)


async def test_agent_error_is_a_failed_case_not_a_crashed_run(make_service: ServiceFactory) -> None:
    result = await run_case(MULTIPLY, make_service([LLMError("provider down")]))

    assert not result.passed
    assert result.failures == ("LLMError: provider down",)


async def test_report_aggregates_metrics_and_is_saved(
    make_service: ServiceFactory, tmp_path: Path
) -> None:
    # One shared script: the first case consumes two turns, the second one turn.
    service = make_service([*MULTIPLY_SCRIPT, say("no idea")])

    report = await run_evals([MULTIPLY, MULTIPLY.model_copy(update={"id": "again"})], service)

    assert report.task_success_rate == 0.5
    assert report.tool_selection_accuracy == 0.5
    saved = save_report(report, tmp_path)
    assert '"task_success_rate": 0.5' in saved.read_text()


@pytest.mark.parametrize(
    ("answer", "passes"),
    [
        ("It is 126.", True),
        ("The result is 126", True),
        ("It is 1260", False),
        ("It is 2126", False),
        ("It is 126.5", False),
        ("It is 0.126", False),
    ],
)
async def test_numeric_facts_match_whole_numbers_only(
    make_service: ServiceFactory, answer: str, passes: bool
) -> None:
    case = EvalCase(id="n", category="happy_path", input="q", expected_facts=("126",))

    result = await run_case(case, make_service([say(answer)]))

    assert result.facts_correct is passes


async def test_an_empty_answer_never_passes(make_service: ServiceFactory) -> None:
    case = EvalCase(id="adv", category="adversarial", input="q", forbidden_facts=("secret",))

    result = await run_case(case, make_service([say("")]))

    assert result.failures == ("empty answer",)

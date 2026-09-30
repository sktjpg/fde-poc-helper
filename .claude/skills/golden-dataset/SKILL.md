---
name: golden-dataset
description: "How to define, extend and run the golden evaluation dataset for the agent, and how to read the results. Use when adding or changing agent behaviour, when asked how we know the agent works, when a bug is found (add a regression case), when choosing metrics, or when asked to build or improve evals."
---

# Golden dataset

A golden dataset is a small, versioned set of inputs with the behaviour we expect, run
against the real agent to get numbers instead of impressions. Unit tests use a scripted
model and prove the code is correct; the golden dataset uses the real model and proves the
system behaves. Both are needed. Full method: `docs/golden-dataset.md`.

## Where it lives

- `app/evaluation/golden_dataset.jsonl`: one JSON object per line.
- `app/evaluation/offline_eval.py`: schema (`EvalCase`), scoring, runner, report.
- `app/evaluation/eval_results/`: one timestamped JSON per run, the tracked history.
- `make eval`: run it against the real model. With `LLM_PROVIDER=claude_code` it uses the
  local Claude Code login instead of an API key.

## Case schema

```json
{"id": "edge-divide-by-zero", "category": "edge_case",
 "input": "Divide 10 by 0 and tell me the result.",
 "expected_tools": ["calculator"], "forbidden_tools": [],
 "expected_facts": ["zero"], "forbidden_facts": ["infinity"],
 "max_steps": 3, "notes": "Tool errors; the agent must explain, not invent a number."}
```

| Field             | Meaning                                                            |
|-------------------|--------------------------------------------------------------------|
| `id`              | Stable, unique, descriptive. Never reuse.                          |
| `category`        | `happy_path`, `edge_case`, `out_of_scope`, `adversarial`, `regression` |
| `input`           | What the user sends, verbatim.                                     |
| `expected_tools`  | Tools that must be used.                                           |
| `forbidden_tools` | Tools that must not be used.                                       |
| `expected_facts`  | Must appear in the answer (case-insensitive; numbers match whole). |
| `forbidden_facts` | Substrings that must not appear (leaks, hallucinated values).      |
| `max_steps`       | Optional efficiency bound.                                         |
| `notes`           | Why the case exists. Required in practice.                         |

Unknown fields are rejected, so a typo in a field name fails loudly.

## Writing good cases

- Assert behaviour and facts, never exact wording. Wording changes with every model.
- Facts are short and unambiguous: a number, an id, a status, a key term.
- Every capability gets a positive case and a negative one (when it must not trigger). Tool
  selection is only tested if both exist.
- Cover the categories: a suite of only happy paths measures nothing useful.
- Each case checks one thing. When it fails, the reason should be obvious.
- Derive cases from the requirement text, from real or realistic user phrasing, and from
  every bug found (category `regression`, note what broke).
- 10 to 30 sharp cases beat 300 vague ones at this stage.

## When a requirement changes

1. Add the cases first: at least one where the new behaviour must happen and one where it
   must not.
2. Implement.
3. Unit and loop tests with `ScriptedLLM` (`make check`).
4. `make eval` and compare with the previous file in `eval_results/`.

## Metrics the runner reports

Task success rate (all checks pass), tool-selection accuracy, average steps, average
latency, total tokens, total cost. An empty answer always fails. A failed case lists exactly which check failed.

Interpretation: success up with steps or cost sharply up is a trade-off to state, not a
win. One run of a non-deterministic system is a sample; for a claim, run it several times
and report the rate.

## Extending the scorer

New deterministic checks (structured-output validity, citation present, groundedness
against retrieved ids) go in `score()` in `offline_eval.py` with a test in
`tests/test_evaluation.py`. Prefer code checks. Use an LLM judge only for qualities code
cannot check (tone, completeness), with a fixed rubric, a cheaper model, and a handful of
human-labelled examples to confirm the judge agrees with a human.

For retrieval, evaluate it separately from generation: each case lists the relevant
document ids and the scorer computes Recall@K and MRR over the retriever output alone.

## What to say aloud

"I don't judge the agent by reading a few outputs. There is a golden set covering happy
paths, edge cases, out-of-scope and adversarial inputs; it scores tool selection and facts,
and every run is stored so a regression shows up as a number."

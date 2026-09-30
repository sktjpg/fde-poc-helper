---
description: Add golden-dataset cases for a behaviour, or run and interpret the evals
argument-hint: <behaviour to cover | "run">
---

Evaluation task: $ARGUMENTS

Load the `golden-dataset` skill.

- If the argument is `run`: confirm with me first (it calls the real model and costs
  tokens), then run `make eval`, show the per-case results and the summary, and compare
  with the previous file in `app/evaluation/eval_results/`.
- Otherwise: add cases covering that behaviour to `app/evaluation/golden_dataset.jsonl`.
  At least one where it must happen and one where it must not; add an edge or adversarial
  case if it touches external data or a consequential action. Extend `score()` only if a
  needed check is missing, with a test. Run `make check`.

Report the cases added and why each exists.

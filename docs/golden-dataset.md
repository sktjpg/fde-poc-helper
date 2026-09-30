# Golden dataset

## What it is

A golden dataset is a small, versioned set of representative inputs, each paired with the
behaviour we expect from the system. We run the real agent over it and get numbers. It is
the agent's regression suite.

It answers a question unit tests cannot. Unit tests replace the model with a script, so
they prove the code around the model is correct. They say nothing about whether the real
model, with our prompt and our tools, picks the right tool and gives the right answer. The
golden dataset measures exactly that.

|                | Unit and loop tests              | Golden dataset                        |
|----------------|----------------------------------|---------------------------------------|
| Model          | Scripted fake                    | Real                                  |
| Deterministic  | Yes                              | No: a run is a sample                 |
| Proves         | The code is correct              | The system behaves as intended        |
| Runs           | On every change, free, fast      | Before and after behaviour changes    |
| Fails when     | There is a bug                   | Prompt, tool or model change degrades behaviour |

"Golden" means the expectations were decided by a person who knows the right answer. The
dataset is ground truth, so it is curated by hand, reviewed like code and kept in git.

## What a case contains

One JSON object per line in `app/evaluation/golden_dataset.jsonl`:

```json
{"id": "edge-divide-by-zero", "category": "edge_case",
 "input": "Divide 10 by 0 and tell me the result.",
 "expected_tools": ["calculator"],
 "expected_facts": ["zero"], "forbidden_facts": ["infinity"],
 "notes": "Tool returns an error; the agent must explain it, not invent a number."}
```

| Field             | What it checks                                               |
|-------------------|--------------------------------------------------------------|
| `input`           | The user message, verbatim                                   |
| `expected_tools`  | Tools that must be called                                    |
| `forbidden_tools` | Tools that must not be called                                |
| `expected_facts`  | Short strings that must appear in the answer (numbers match whole: 126 is not found in 1260) |
| `forbidden_facts` | Strings that must not appear: leaks, invented values         |
| `max_steps`       | Optional ceiling on agent steps (efficiency)                 |
| `category`, `notes` | What kind of risk the case covers and why it exists        |

We assert behaviour (which tools) and facts (numbers, ids, statuses), never exact wording.
Wording changes with every model and prompt revision; the facts should not.

## How to build one

1. List the behaviours. Read the requirement and write one line per thing the system must
   do and per thing it must never do. Each line becomes one or more cases.
2. Cover five categories. A set of only happy paths measures nothing.

   | Category       | Question it answers                          | Example                               |
   |----------------|----------------------------------------------|---------------------------------------|
   | `happy_path`   | Does the core flow work?                     | A clear request that needs the tool   |
   | `edge_case`    | Does it cope with bad or missing data?       | Tool error, empty result, ambiguity   |
   | `out_of_scope` | Does it avoid acting when it should not?     | A request that needs no tool          |
   | `adversarial`  | Does it resist misuse?                       | Injection, request to leak the prompt |
   | `regression`   | Does a fixed bug stay fixed?                 | The exact input that broke            |

3. Write a positive and a negative for every capability. "Uses the invoice tool when the user
   asks about a specific invoice" needs a specific-invoice case (tool expected) and a
   general-billing-question case (tool forbidden). Without the negative, a model that always calls the tool passes.
4. Use realistic phrasing. Real users are terse, vague and make typos. If real queries or
   transcripts exist, sample from them; otherwise write a few variants of each intent.
5. Make expectations checkable by code. A number, an id, a status, a key term. If the only
   way to check is "reads well", it needs a rubric and a judge (below), or it is not a
   golden case.
6. Keep it small and sharp. 10 to 30 cases is right for a new feature. Each case checks one
   thing so that a failure points at its cause.
7. Review it like code. Someone who knows the domain confirms the expectations are right.
   A wrong golden case is worse than a missing one.
8. Grow it from failures. Every bug found by hand or in production becomes a `regression`
   case before it is fixed.

Where cases come from, in order of value: production traces and user feedback, domain
experts, the requirement text, and model-generated variations (useful for volume, but every
generated case is reviewed by a person before it counts as golden).

## Running and reading it

```bash
make eval        # real model: API key, or LLM_PROVIDER=claude_code for the local login
```

The runner (`app/evaluation/offline_eval.py`) prints one PASS or FAIL line per case with the
exact check that failed, a summary, and saves the run to `app/evaluation/eval_results/`.

| Metric                  | Meaning                                        |
|-------------------------|------------------------------------------------|
| Task success rate       | Cases where every check passed                 |
| Tool-selection accuracy | Cases where expected tools were used and forbidden ones were not |
| Average steps           | Efficiency of the loop                         |
| Latency, tokens, cost   | What the behaviour costs                       |

How to read it:

- Compare against the previous saved run, not against 100%. The question is "did this
  change make it better or worse?".
- Look at failures by category. Happy paths passing with adversarial failing is a different
  problem from the reverse.
- Quality up with cost or steps sharply up is a trade-off to state, not a free win.
- The model is non-deterministic. For a claim that matters, run the set several times and
  report the pass rate per case. A case that passes 7 times out of 10 is a finding.

## When a requirement changes

1. Add the cases first: what must now happen, and what must still not happen.
2. Implement.
3. `make check` (unit and loop tests with the scripted model).
4. `make eval`, compare with the last run, keep the new result file.

## Beyond string checks

- Structured output: validate the answer against its Pydantic model; validity rate is a
  metric.
- Groundedness (RAG): every citation must point at a chunk that was retrieved; claims must
  be supported by those chunks.
- Retrieval, evaluated separately from generation: each case lists the relevant document
  ids; compute Recall@K and MRR on the retriever alone. If recall is low, no prompt change
  will fix the answers.
- LLM as judge, only for qualities code cannot check (tone, completeness, helpfulness): a
  fixed rubric with a small scale, a cheaper model, and a set of human-labelled examples to
  confirm the judge agrees with people before trusting its scores.

## Offline and online

Offline evaluation (this document) runs a fixed set before shipping. Online monitoring
watches real traffic after shipping: sampled runs, error and stall rates, steps, cost,
latency, user feedback tied to trace ids. The two feed each other: surprising production
failures become golden cases.

## Pitfalls

- Only happy paths.
- Asserting exact sentences, so every prompt tweak breaks the suite.
- No negative cases, so over-eager tool use is invisible.
- Tuning the prompt until the set passes and calling it done: that is overfitting to the
  set. Keep some cases you do not look at while tuning.
- Treating one green run as proof.
- Letting the set rot: cases for removed behaviour, none for new behaviour.

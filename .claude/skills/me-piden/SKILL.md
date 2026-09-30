---
name: me-piden
description: "Implement a new requirement end to end. Use when the user writes \"Me piden esto: ...\" or gives a requirement (possibly a file under brief/) to build: analyse it, state the approach briefly, implement the smallest correct solution, add tests, run make check and explain the decision."
---

The new requirement is whatever the user wrote with this command or after "Me piden esto:".

If it names a file (for example under `brief/`), read that file first: it is the statement.

Follow the "Me piden esto" procedure in CLAUDE.md:

1. Technical requirements: inputs, outputs, constraints, edge cases, failure modes, and
   whether each part should be deterministic code or an LLM.
2. Inspect the relevant code, tests and dependencies. Load the matching skill if one applies.
3. Tell me the approach in 2 to 5 sentences, including the main trade-off and any
   assumption you are making. Then go ahead without waiting.
4. Implement the smallest correct solution in small steps.
5. Add or update tests, and a golden case when agent behaviour changes.
6. Run `make check` and fix failures at the root cause.
7. Report: what changed (files), what you verified, anything not done or not verified.
8. Finish with one or two sentences in English I can say aloud to explain the decision.

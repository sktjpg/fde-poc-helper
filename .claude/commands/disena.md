---
description: Scope an open-ended or customer-shaped requirement into a design before coding
argument-hint: <the problem, or a path under brief/>
---

Scope this before any code is written:

$ARGUMENTS

If it names a file (for example under `brief/`), that file is the statement.

Use the `solution-architect` sub-agent. Pass it the requirement verbatim and the file path
if there is one.

Then give me, compactly:

1. The problem in one or two sentences.
2. Assumptions, and at most three questions worth asking the customer.
3. Which steps are deterministic and which need an LLM, with the reason.
4. The design mapped to our layers and the data flow.
5. The slice to build first, in order, and what is deferred.
6. Risks with mitigations, and the golden cases that will prove it works.
7. Two or three sentences I can say aloud.

Do not start implementing until I say so.

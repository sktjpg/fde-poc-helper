---
name: disena
description: "Scope an open-ended or customer-shaped problem into a design before any code. Use when the user writes \"Diseña: ...\" or hands over a business problem or brief that needs scoping: deterministic vs LLM split, components, first slice, risks, how to prove it works."
---

The problem to scope is whatever the user wrote with this command or after "Diseña:".

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

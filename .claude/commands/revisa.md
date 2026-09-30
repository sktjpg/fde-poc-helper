---
description: Code review of the current change, real problems first
argument-hint: [file or area; defaults to the uncommitted changes]
---

Review: $ARGUMENTS

If nothing is specified, review the uncommitted changes (`git diff` and `git diff --staged`).

Use the `agentic-reviewer` sub-agent so the review is independent of the reasoning that
produced the code. Give it the scope and the requirement the change was meant to satisfy,
not your own conclusions about it.

When it reports back, give me:

- the verdict in one line,
- the findings ranked by severity with `file:line`, trigger and smallest fix,
- which ones you recommend fixing now.

Do not fix anything until I say which.

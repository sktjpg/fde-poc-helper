---
description: Reduce complexity while preserving behaviour, so the code is easy to explain live
argument-hint: [file or area; defaults to the last change]
---

Simplify: $ARGUMENTS

If nothing is specified, target the most recent change.

Goal: the same behaviour with less to explain.

1. Run `make check` first so there is a green baseline.
2. Look for: abstractions with a single use, indirection that hides a simple flow,
   configuration nobody needs yet, duplicated logic, dependencies that a few lines of
   standard library would replace, functions doing two things.
3. Tell me what you will remove or merge and what stays, in a few lines, then do it.
4. Do not change behaviour, public contracts or tests' expectations. Keep the termination
   bounds, validation and error handling: those are not complexity to cut.
5. Run `make check` again. Report what got simpler and the before/after in files or lines.

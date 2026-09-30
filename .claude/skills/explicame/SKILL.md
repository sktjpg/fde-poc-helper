---
name: explicame
description: "Explain code and its design decisions, ready to present, without modifying anything. Use when the user writes \"Explícame\" or asks why something was built this way, what the alternatives and trade-offs are, or which questions to expect."
---

Explain what the user named with this command.

If nothing is specified, explain the most recent change (`git diff`, or the last files you
edited in this session).

Do not modify any code. Cover:

1. What it does: the real control flow, step by step, with `file:line` references.
2. Why we chose this approach.
3. Alternatives and their trade-offs.
4. What it does not handle.
5. The follow-up questions I am likely to be asked, each with a short answer.
6. A 30-second summary in English I can say aloud.

Keep it tight: I will be reading this while talking.

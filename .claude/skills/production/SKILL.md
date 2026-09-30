---
name: production
description: "Production-readiness review: the highest-impact gaps first, nothing implemented automatically. Use when the user writes \"Production\" or asks what is missing to ship, scale or operate the current solution."
---

Review the current solution as if it were going to production. If the user named an area with this command, focus on it.

Use the `production-auditor` sub-agent for an independent assessment of the code as it is.

Then give me:

1. A one-line verdict.
2. The top five gaps by impact, each with the production failure it would cause, the
   smallest change that closes it and the effort.
3. What is already solid.
4. The one you would implement now, and why.

Do not implement anything until I choose.

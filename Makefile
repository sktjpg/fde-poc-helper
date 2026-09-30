.PHONY: check test lint types run eval cursor up up-api dev down nuke

# Parameters of the local Docker stack: ports and the throwaway Langfuse credentials.
LOCAL_ENV = docker/local.env
COMPOSE = docker compose --env-file $(LOCAL_ENV)
LOAD_LOCAL_ENV = set -a && . ./$(LOCAL_ENV) && set +a

check: lint types test

test:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check . && uv run python scripts/sync_cursor.py --check

types:
	uv run mypy

run:
	uv run uvicorn app.main:app --reload

eval:
	uv run python -m app.evaluation.offline_eval

# Local Langfuse in Docker. Waits until it answers, then prints where to look.
up:
	$(COMPOSE) up -d
	@$(LOAD_LOCAL_ENV) && printf 'Waiting for Langfuse' && \
	for attempt in $$(seq 1 90); do \
		curl -fsS -o /dev/null "$$LANGFUSE_HOST/api/public/health" 2>/dev/null && break; \
		printf '.'; sleep 2; \
	done && \
	curl -fsS -o /dev/null "$$LANGFUSE_HOST/api/public/health" && \
	printf '\nLangfuse: %s  (login %s / %s)\n' "$$LANGFUSE_HOST" "$$LANGFUSE_USER_EMAIL" "$$LANGFUSE_USER_PASSWORD"

# The API on this machine (so LLM_PROVIDER=claude_code works), tracing to the local Langfuse.
# Variables set here win over .env.
dev: up
	$(LOAD_LOCAL_ENV) && uv run uvicorn app.main:app --reload --port "$$APP_PORT"

# Everything in containers, API included. Needs ANTHROPIC_API_KEY in .env.
up-api:
	$(COMPOSE) --profile api up -d --build

down:
	$(COMPOSE) --profile api down

# Also deletes the stored traces.
nuke:
	$(COMPOSE) --profile api down --volumes

# Regenerate .cursor/ from CLAUDE.md and .claude/ after editing them.
cursor:
	uv run python scripts/sync_cursor.py

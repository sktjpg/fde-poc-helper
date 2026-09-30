.PHONY: check test lint types run eval cursor up up-api dev down nuke

# Which Docker stack the targets below act on: docker/$(STACK).env holds its parameters
# (where Docker runs, ports, Langfuse credentials). `make up STACK=gmktec` uses another one.
STACK ?= local
STACK_ENV = docker/$(STACK).env
# Loaded into the shell first so that DOCKER_HOST, when the stack sets it, reaches docker.
LOAD_STACK_ENV = set -a && . ./$(STACK_ENV) && set +a
COMPOSE = $(LOAD_STACK_ENV) && docker compose --env-file $(STACK_ENV)

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

# Langfuse in Docker. Waits until it answers, then prints where to look.
up:
	$(COMPOSE) up -d
	@$(LOAD_STACK_ENV) && printf 'Waiting for Langfuse' && \
	for attempt in $$(seq 1 90); do \
		curl -fsS -o /dev/null "$$LANGFUSE_HOST/api/public/health" 2>/dev/null && break; \
		printf '.'; sleep 2; \
	done && \
	curl -fsS -o /dev/null "$$LANGFUSE_HOST/api/public/health" && \
	printf '\nLangfuse: %s  (login %s / %s)\n' "$$LANGFUSE_HOST" "$$LANGFUSE_USER_EMAIL" "$$LANGFUSE_USER_PASSWORD"

# The API on this machine (so LLM_PROVIDER=claude_code works), tracing to the stack's Langfuse.
# Variables set here win over .env.
dev: up
	$(LOAD_STACK_ENV) && uv run uvicorn app.main:app --reload --port "$$APP_PORT"

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

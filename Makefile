.PHONY: check test lint types run eval cursor

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

# Regenerate .cursor/ from CLAUDE.md and .claude/ after editing them.
cursor:
	uv run python scripts/sync_cursor.py

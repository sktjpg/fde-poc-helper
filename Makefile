.PHONY: check test lint types run eval

check: lint types test

test:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check .

types:
	uv run mypy

run:
	uv run uvicorn app.main:app --reload

eval:
	uv run python -m app.evaluation.offline_eval

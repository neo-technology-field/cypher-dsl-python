.DEFAULT_GOAL := help

.PHONY: help deps test test-cov lint format format-check typing docs package cypher-audit matrix

help:  ## Show the available targets.
	@awk 'BEGIN {FS = ":.*## "; printf "Targets:\n"} /^[a-z-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

deps:  ## Install the locked development and test groups.
	uv sync --group dev --group test

test:  ## Run the unit suite on the current interpreter.
	uv run --frozen pytest

test-cov:  ## Run the unit suite on the current interpreter and report coverage.
	uv run --frozen pytest --cov=cypher_dsl --cov-report=term-missing

lint:  ## Check the source with Ruff.
	uv run --frozen ruff check .

format:  ## Format the source with Ruff.
	uv run --frozen ruff format .

format-check:  ## Check formatting without writing.
	uv run --frozen ruff format --check .

typing:  ## Run mypy in strict mode.
	uv run --frozen mypy

docs:  ## Build the documentation without network access.
	uv run --frozen nox -s docs

package:  ## Build an sdist and wheel, then smoke the installed wheel.
	uv run --frozen nox -s package

cypher-audit:  ## Check rendered statements against a running server (NEO4J_PASSWORD required).
	uv run --frozen --group audit python -m tools.check_cypher

matrix:  ## Run every unique Nox job once through the aggregate session.
	uv run --frozen nox -s matrix

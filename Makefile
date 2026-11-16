.DEFAULT_GOAL := help

.PHONY: help deps test test-cov lint format format-check typing docs package cypher-audit matrix

help:  ## Show the available targets.
	@awk 'BEGIN {FS = ":.*## "; printf "Targets:\n"} /^[a-z-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

deps:  ## Install the locked development and test groups.
	uv sync --group dev --group test

test:  ## Run the unit suite on the current interpreter.
	uv run --group test pytest

test-cov:  ## Run the unit suite on the current interpreter and report coverage.
	uv run --group test pytest --cov=cypher_dsl --cov-report=term-missing

lint:  ## Check the source with Ruff.
	uv run ruff check .

format:  ## Format the source with Ruff.
	uv run ruff format .

format-check:  ## Check formatting without writing.
	uv run ruff format --check .

typing:  ## Run mypy in strict mode.
	uv run mypy

docs:  ## Build the documentation without network access.
	uv run nox -s docs

package:  ## Build an sdist and wheel, then smoke the installed wheel.
	uv run nox -s package

cypher-audit:  ## Check rendered statements against a running server (NEO4J_PASSWORD required).
	uv run --group audit python -m tools.check_cypher

matrix:  ## Run every unique Nox job once through the aggregate session.
	uv run nox -s matrix

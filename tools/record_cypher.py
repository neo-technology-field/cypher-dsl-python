"""
Record every statement rendered while a pytest session runs.

Loaded with ``-p tools.record_cypher``, the plugin replaces ``Renderer.render`` for the
duration of the session and keeps each result. Nothing is written to disk: the tool that
loads this plugin reads ``RECORDS`` in the same process, so parameter values keep their
Python types instead of passing through JSON.
"""

from __future__ import annotations

from typing import Any

import pytest

RECORDS: list[dict[str, Any]] = []

_ORIGINAL_RENDER = None
_CURRENT_TEST = {"nodeid": ""}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--record-cypher",
        action="store_true",
        default=False,
        help="Keep every rendered statement in tools.record_cypher.RECORDS.",
    )


def pytest_runtest_setup(item: pytest.Item) -> None:
    _CURRENT_TEST["nodeid"] = item.nodeid


def pytest_configure(config: pytest.Config) -> None:
    if not config.getoption("--record-cypher"):
        return
    from cypher_dsl import Renderer

    global _ORIGINAL_RENDER
    _ORIGINAL_RENDER = Renderer.render

    def render(self: Renderer, query: object) -> Any:
        rendered = _ORIGINAL_RENDER(self, query)
        RECORDS.append(
            {
                "cypher": rendered.cypher,
                "parameters": dict(rendered.parameters),
                "unbound": set(rendered.unbound_parameters),
                "test": _CURRENT_TEST["nodeid"],
            }
        )
        return rendered

    Renderer.render = render


def pytest_unconfigure(config: pytest.Config) -> None:
    if _ORIGINAL_RENDER is None:
        return
    from cypher_dsl import Renderer

    Renderer.render = _ORIGINAL_RENDER

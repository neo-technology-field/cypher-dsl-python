"""Construct renderers for filters attached to their owning clause."""

from __future__ import annotations

from cypher_dsl.clauses.match import Where
from cypher_dsl.render.context import RenderContext
from cypher_dsl.render.fragments import Fragment
from cypher_dsl.render.rules import RuleBinding, bind


def where(node: Where, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a filter attached to its owning clause."""
    return f"WHERE {children[0].text}"


def filter_bindings() -> tuple[RuleBinding, ...]:
    """Return the filter construct renderers."""
    return (bind(Where, where),)


__all__ = ["filter_bindings"]

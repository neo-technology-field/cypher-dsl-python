"""
Projection clauses and the modifiers each projection owns.

``WITH`` and ``RETURN`` share one projection body: at least one item, optional
``DISTINCT``, one ordering list and a single ``SKIP`` and ``LIMIT`` position. One
definition means the two clauses cannot render different grammar.

``WITH`` adds a filter, which Cypher places after the ordering and pagination modifiers.
Storing the filter inside the clause, rather than as a free-standing node, is what keeps
the clause sequence immutable and the rendered order fixed.
"""

from __future__ import annotations

from cypher_dsl.clauses.projection import ReturnClause, WithClause
from cypher_dsl.render.context import RenderContext
from cypher_dsl.render.fragments import Fragment
from cypher_dsl.render.rules import RuleBinding, bind


def projection(node: ReturnClause | WithClause, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a projection whose WITH filter follows its ordering and pagination."""
    distinct = "DISTINCT " if node.distinct else ""
    items = ", ".join(child.text for child in children[: len(node.expressions)])
    text = f"{node.keyword} {distinct}{items}"
    index = len(node.expressions)
    if node.order_by:
        ordered = children[index : index + len(node.order_by)]
        text = f"{text} ORDER BY {', '.join(child.text for child in ordered)}"
        index += len(node.order_by)
    if node.skip is not None:
        text = f"{text} SKIP {children[index].text}"
        index += 1
    if node.limit is not None:
        text = f"{text} LIMIT {children[index].text}"
        index += 1
    if isinstance(node, WithClause) and node.where is not None:
        text = f"{text} {children[index].text}"
    return text


def projection_bindings() -> tuple[RuleBinding, ...]:
    """Return the projection construct renderers."""
    return (
        bind(ReturnClause, projection),
        bind(WithClause, projection),
    )


__all__ = ["projection_bindings"]

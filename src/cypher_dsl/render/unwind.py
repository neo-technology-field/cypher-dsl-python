"""Construct renderers for the UNWIND clause."""

from __future__ import annotations

from cypher_dsl.clauses.unwind import UnwindClause
from cypher_dsl.render.context import RenderContext
from cypher_dsl.render.fragments import Fragment
from cypher_dsl.render.literals import quote_identifier
from cypher_dsl.render.rules import RuleBinding, bind


def unwind_clause(node: UnwindClause, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render an UNWIND source and its quoted variable declaration."""
    alias = quote_identifier(node.variable.symbol.value, context.always_escape_names)
    return f"UNWIND {children[0].text} AS {alias}"


def unwind_bindings() -> tuple[RuleBinding, ...]:
    """Return the UNWIND construct renderers."""
    return (bind(UnwindClause, unwind_clause),)


__all__ = ["unwind_bindings"]

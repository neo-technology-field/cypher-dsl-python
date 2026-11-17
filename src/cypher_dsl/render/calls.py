"""Construct renderers for the ``CALL`` subquery clause."""

from __future__ import annotations

from cypher_dsl.clauses.call import SubqueryCallClause
from cypher_dsl.render.context import RenderContext
from cypher_dsl.render.fragments import Fragment
from cypher_dsl.render.literals import quote_identifier
from cypher_dsl.render.rules import RuleBinding, bind


def subquery_call_clause(node: SubqueryCallClause, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render CALL or OPTIONAL CALL with its scope clause, body and transaction modifier."""
    layout = context.layout
    keyword = "OPTIONAL CALL" if node.optional else "CALL"
    if node.import_all:
        header = layout.parenthesized(keyword, ["*"])
    elif node.imports:
        names = [quote_identifier(item.symbol.value, context.always_escape_names) for item in node.imports]
        header = layout.parenthesized(keyword, names)
    else:
        header = layout.tokens(keyword, "()")
    text = layout.body(header, children[0].text)
    if node.in_transactions:
        text = layout.tokens(text, "IN TRANSACTIONS")
        if node.of_rows is not None:
            text = layout.tokens(text, "OF", children[1].text, "ROWS")
    return text


def call_bindings() -> tuple[RuleBinding, ...]:
    """Return the CALL subquery construct renderers."""
    return (bind(SubqueryCallClause, subquery_call_clause),)


__all__ = ["call_bindings"]

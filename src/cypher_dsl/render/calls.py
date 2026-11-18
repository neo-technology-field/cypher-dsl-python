"""Construct renderers for the ``CALL`` subquery clause and the procedure call."""

from __future__ import annotations

from cypher_dsl.clauses.call import ProcedureCallClause, SubqueryCallClause
from cypher_dsl.render.context import RenderContext
from cypher_dsl.render.fragments import Fragment
from cypher_dsl.render.literals import quote_function_segment, quote_identifier
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


def procedure_call_clause(node: ProcedureCallClause, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """
    Render ``CALL`` or ``OPTIONAL CALL`` with its arguments, its ``YIELD`` items and its filter.

    Parentheses are always rendered, including the empty argument list of ``CALL db.labels()``. A filter follows the
    ``YIELD`` item list as the clause's owned ``WHERE``, as in
    ``CALL dbms.checkConfigValue($setting, 'true') YIELD valid AS ok WHERE ok = true``. A call without yield items
    renders no ``YIELD`` and holds no filter.

    Args:
        node: The procedure call clause.
        children: The fragments of the arguments, the yield items and the predicate.
        context: The render context, supplying the layout.

    Returns:
        The rendered clause text.
    """
    layout = context.layout
    keyword = "OPTIONAL CALL" if node.optional else "CALL"
    argument_count = len(node.arguments)
    yield_count = len(node.yields)
    arguments = [child.text for child in children[:argument_count]]
    name = ".".join(quote_function_segment(segment) for segment in node.name)
    text = layout.tokens(keyword, f"{name}({layout.series(arguments)})")
    if yield_count:
        items = [child.text for child in children[argument_count : argument_count + yield_count]]
        text = layout.listed(f"{text} YIELD", items)
    if node.predicate is not None:
        predicate = children[argument_count + yield_count].text
        text = layout.owned(text, layout.tokens("WHERE", predicate))
    return text


def call_bindings() -> tuple[RuleBinding, ...]:
    """Return the CALL subquery and procedure call construct renderers."""
    return (
        bind(SubqueryCallClause, subquery_call_clause),
        bind(ProcedureCallClause, procedure_call_clause),
    )


__all__ = ["call_bindings"]

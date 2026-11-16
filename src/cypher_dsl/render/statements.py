"""Construct renderers for pattern matching, statements and shared rule assembly."""

from __future__ import annotations

from cypher_dsl.clauses.match import MatchClause
from cypher_dsl.errors import DslError
from cypher_dsl.render.context import RenderContext
from cypher_dsl.render.expressions import expression_bindings
from cypher_dsl.render.filters import filter_bindings
from cypher_dsl.render.fragments import Fragment
from cypher_dsl.render.patterns import pattern_bindings
from cypher_dsl.render.projections import projection_bindings
from cypher_dsl.render.rules import RuleBinding, bind
from cypher_dsl.render.unwind import unwind_bindings
from cypher_dsl.render.updates import update_bindings
from cypher_dsl.statements.composition import Statement, UnionStatement


def match_clause(node: MatchClause, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render MATCH or OPTIONAL MATCH with its patterns and attached filter."""
    keyword = "OPTIONAL MATCH" if node.optional else "MATCH"
    pattern_text = ", ".join(child.text for child in children[: len(node.patterns)])
    text = f"{keyword} {pattern_text}"
    if node.where is not None:
        text = f"{text} {children[len(node.patterns)].text}"
    return text


def statement(node: Statement, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a non-empty statement with spaces between its clauses."""
    if not children:
        raise DslError("A statement needs at least one clause before it can be rendered.")
    return " ".join(child.text for child in children)


def union_statement(node: UnionStatement, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render statement branches joined by UNION or UNION ALL."""
    separator = " UNION ALL " if node.all else " UNION "
    return separator.join(child.text for child in children)


def statement_bindings() -> tuple[RuleBinding, ...]:
    """Return the MATCH, statement and union construct renderers."""
    return (
        bind(MatchClause, match_clause),
        bind(Statement, statement),
        bind(UnionStatement, union_statement),
    )


def shared_bindings() -> tuple[RuleBinding, ...]:
    """Return every rule binding the renderer uses."""
    return (
        *expression_bindings(),
        *pattern_bindings(),
        *filter_bindings(),
        *projection_bindings(),
        *unwind_bindings(),
        *update_bindings(),
        *statement_bindings(),
    )


__all__ = ["shared_bindings", "statement_bindings"]

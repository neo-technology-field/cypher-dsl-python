"""
Finalised statements and their unions.

A statement is the clause sequence a renderer accepts. It stores no parameter bindings:
those are collected per render, so a statement is reusable and safe to share.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cypher_dsl.clauses.base import Clause
from cypher_dsl.clauses.projection import ReturnClause
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.functions import Asterisk, RawExpression
from cypher_dsl.expressions.values import AliasedExpression, Variable
from cypher_dsl.statements.scope import _scope_after
from cypher_dsl.statements.validation import _validate_statement_clauses
from cypher_dsl.syntax import AstNode, _require_tuple

if TYPE_CHECKING:
    from cypher_dsl.statements.builder import StatementBuilder


@dataclass(frozen=True, weakref_slot=True, slots=True)
class Statement(AstNode):
    """
    A finalised clause sequence that a renderer renders as Cypher text, with no ``UNION``.

    Construction validates the clause sequence, so every path that can produce a
    statement carries the same grammar checks. Frozen containers alone do not certify
    that a sequence is a valid statement.

    Attributes:
        clauses: Clauses in rendered order.
    """

    clauses: tuple[Clause, ...]

    def __post_init__(self) -> None:
        """Reject a clause sequence that is not a valid statement."""
        _require_tuple(self.clauses, "Statement clauses")
        _validate_statement_clauses(self.clauses)

    def children(self) -> tuple[AstNode, ...]:
        """Expose the clauses in their rendered order."""
        return self.clauses


@dataclass(frozen=True, weakref_slot=True, slots=True)
class UnionStatement(AstNode):
    """
    Two or more statements combined with ``UNION`` or ``UNION ALL``.

    Construction validates arity and projection compatibility, so a union built
    directly carries the same checks as one built by :func:`union`.

    Attributes:
        parts: Finalised statements in rendered order.
        all: Whether ``UNION ALL`` keeps duplicates instead of ``UNION`` removing them.
    """

    parts: tuple[Statement, ...]
    all: bool = False

    def __post_init__(self) -> None:
        """Reject a union that is incomplete or has incompatible projections."""
        _require_tuple(self.parts, "UNION parts")
        _validate_union_parts(self.parts)

    def children(self) -> tuple[AstNode, ...]:
        """Expose the union branches in their rendered order."""
        return self.parts


def union(*parts: Statement | StatementBuilder, all: bool = False) -> UnionStatement:
    """
    Combine finalised statements with ``UNION`` or ``UNION ALL``.

    Statement builders are finalised through their own ``build`` path, so an incomplete
    builder cannot reach a renderer as half a union. Known projection names must line
    up by position. A name that cannot be determined without rendering, such as a bare
    literal, is not compared.

    Args:
        parts: At least two statements or statement builders.
        all: Use ``UNION ALL`` when true, otherwise ``UNION``.

    Returns:
        A union statement holding finalised branches.

    Raises:
        DslError: If fewer than two parts are supplied, a part is not finalisable, or
            known projection names disagree.
    """
    from cypher_dsl.statements.builder import StatementBuilder

    statements: list[Statement] = []
    for part in parts:
        if isinstance(part, StatementBuilder):
            statements.append(part.build())
        elif isinstance(part, Statement):
            statements.append(part)
        else:
            raise DslError(f"UNION accepts statements and statement builders, not {type(part).__name__}.")
    return UnionStatement(tuple(statements), all)


def _validate_union_parts(parts: tuple[Statement, ...]) -> None:
    if len(parts) < 2:
        raise DslError("UNION requires at least two statements.")
    for part in parts:
        if not isinstance(part, Statement):
            raise DslError(f"UNION accepts statements, not {type(part).__name__}.")
    _validate_union_projections(parts)


def _validate_union_projections(parts: tuple[Statement, ...]) -> None:
    width: int | None = None
    known_names: list[str | None] = []
    for part in parts:
        columns = _projection_columns(part)
        if columns is None:
            continue
        if width is None:
            width = len(columns)
            known_names.extend([None] * width)
        elif len(columns) != width:
            raise DslError(
                f"UNION branches project {width} and {len(columns)} columns. Branches must project the same width."
            )
        for index, name in enumerate(columns):
            if name is None:
                continue
            known = known_names[index]
            if known is None:
                known_names[index] = name
            elif known != name:
                raise DslError(f"UNION projection names are incompatible: {known!r} and {name!r}.")


def _projection_columns(statement: Statement) -> tuple[str | None, ...] | None:
    """
    Return the result columns of a union branch, or ``None`` when the width is unknown.

    A wildcard keeps a known width by expanding the scope in front of ``RETURN``. A
    single wildcard column has only one possible name, so that name is preserved. A
    multi-column wildcard keeps its positions uncertain, because this library does not
    track the server's column order for ``*``. Trusted raw text may stand for more than
    one column, so it makes the width unknown.
    """
    if not statement.clauses:
        raise DslError("UNION requires each part to end with a RETURN clause.")
    owner = statement.clauses[-1]
    if not isinstance(owner, ReturnClause):
        raise DslError("UNION requires each part to end with a RETURN clause.")
    scope = _scope_after(statement.clauses[:-1])
    columns: list[str | None] = []
    for expression in owner.expressions:
        if isinstance(expression, Asterisk):
            if scope.names is None or not statement.clauses[:-1]:
                return None
            if len(scope.names) == 1:
                columns.append(scope.names[0])
            else:
                columns.extend([None] * len(scope.names))
        elif isinstance(expression, AliasedExpression):
            columns.append(expression.alias_name.value)
        elif isinstance(expression, RawExpression):
            return None
        elif isinstance(expression, Variable):
            columns.append(expression.symbol.value)
        else:
            columns.append(None)
    return tuple(columns)


__all__ = [
    "Statement",
    "UnionStatement",
    "union",
]

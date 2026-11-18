"""
Finalised statements and their unions.

A statement is the clause sequence a renderer accepts. It stores no parameter bindings:
those are collected per render, so a statement is reusable and safe to share.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cypher_dsl.ast import AstNode, _require_tuple
from cypher_dsl.clauses.base import Clause
from cypher_dsl.errors import DslError
from cypher_dsl.statements.frames import ScopeFrame

if TYPE_CHECKING:
    from cypher_dsl.statements.builder import StatementBuilder


@dataclass(frozen=True, weakref_slot=True, slots=True)
class Statement(AstNode):
    """
    A finalised clause sequence that a renderer renders as Cypher text, with no ``UNION``.

    Construction validates the clause sequence, so every path that can produce a
    statement carries the same grammar checks. The private open-body route that ``union``
    and ``exists`` finalise builders through is the one exception: it runs every check
    except the final-clause rule. Frozen containers alone do not certify that a sequence
    is a valid statement.

    Attributes:
        clauses: Clauses in rendered order.
    """

    clauses: tuple[Clause, ...]

    def __post_init__(self) -> None:
        """Reject a clause sequence that is not a valid statement."""
        from cypher_dsl.statements.validation import _validate_statement_clauses

        _require_tuple(self.clauses, "Statement clauses")
        _validate_statement_clauses(self.clauses)

    def children(self) -> tuple[AstNode, ...]:
        """Expose the clauses in their rendered order."""
        return self.clauses


class _OpenStatement(Statement):
    """
    A statement finalised without the final-clause rule.

    ``union`` and ``exists`` hold bodies a construct may legally end open, so they
    finalise builders through this class. Every other path, including ``build()``,
    keeps the final-clause rule: a standalone statement still ends in ``RETURN`` or a
    write clause.
    """

    __slots__ = ()

    def __post_init__(self) -> None:
        """Run the order checks and the scope walk without the final-clause rule."""
        from cypher_dsl.statements.rules import walk_clauses
        from cypher_dsl.statements.validation import _validate_clause_order

        _require_tuple(self.clauses, "Statement clauses")
        _validate_clause_order(self.clauses)
        walk_clauses(self.clauses)


@dataclass(frozen=True, weakref_slot=True, slots=True)
class UnionStatement(AstNode):
    """
    Two or more statements combined with ``UNION`` or ``UNION ALL``.

    Construction validates arity, branch shape and projection compatibility, so a union
    built directly carries the same checks as one built by :func:`union`. A union projects
    in every branch or in none; whether a union that projects nothing is acceptable is a
    question for the context that renders it.

    Attributes:
        parts: Finalised statements in rendered order.
        all: Whether ``UNION ALL`` keeps duplicates instead of ``UNION`` removing them.
    """

    parts: tuple[Statement, ...]
    all: bool = False

    def __post_init__(self) -> None:
        """
        Reject an incomplete union or one whose branch shapes disagree.

        A union projects in every branch or in none. The all-or-none shape is a
        construction rule because it does not depend on context; whether a union that
        projects nothing is acceptable is a question for the context that renders it.
        """
        from cypher_dsl.statements.rules.flow import union_columns_check

        _require_tuple(self.parts, "UNION parts")
        _validate_union_parts(self.parts)
        if _every_branch_returns(self.parts):
            union_columns_check(self.parts, ScopeFrame())

    def children(self) -> tuple[AstNode, ...]:
        """Expose the union branches in their rendered order."""
        return self.parts


def union(*parts: Statement | StatementBuilder, all: bool = False) -> UnionStatement:
    """
    Combine finalised statements with ``UNION`` or ``UNION ALL``.

    A union projects in every branch or in none. Known projection names must line up by
    position when every branch ends in ``RETURN``; a union whose branches all end open is
    a unit body, legal inside ``EXISTS`` and rejected when rendered as a standalone
    query. A name that cannot be determined without rendering, such as a bare literal, is
    not compared.

    Builder parts are finalised without the final-clause rule, because a union body may
    end open inside ``EXISTS``. A standalone union that projects nothing is rejected when
    rendered. Statement parts are taken as given.

    Args:
        parts: At least two statements or statement builders.
        all: Use ``UNION ALL`` when true, otherwise ``UNION``.

    Returns:
        A union statement holding finalised branches.

    Raises:
        DslError: If fewer than two parts are supplied, a part is not finalisable, the
            branches mix a final ``RETURN`` with branches that end without one, or known
            projection names disagree.
    """
    from cypher_dsl.statements.builder import StatementBuilder

    statements: list[Statement] = []
    for part in parts:
        if isinstance(part, StatementBuilder):
            statements.append(_open_statement(part))
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


def _branches(subquery: Statement | UnionStatement) -> tuple[Statement, ...]:
    """Return the statements a subquery holds: one, or the branches of a union."""
    return subquery.parts if isinstance(subquery, UnionStatement) else (subquery,)


def _every_branch_returns(parts: tuple[Statement, ...]) -> bool:
    """
    Return whether every branch ends in a RETURN clause, and reject a mixed union.

    Raises:
        DslError: If some branches end in ``RETURN`` and others do not, or a branch has
            no clauses. A union projects in every branch or in none; the grammar has no
            union that mixes the two.
    """
    from cypher_dsl.clauses.projection import ReturnClause

    returning: list[bool] = []
    for part in parts:
        if not part.clauses:
            raise DslError("UNION requires each part to end with a RETURN clause.")
        returning.append(isinstance(part.clauses[-1], ReturnClause))
    if any(returning) and not all(returning):
        raise DslError(
            "UNION branches mix a final RETURN with branches that end without one. "
            "All branches must end with a RETURN clause, or none must."
        )
    return all(returning)


def _open_statement(builder: StatementBuilder) -> Statement:
    """Finalise a builder as an open body: the sequence checks, without the final-clause rule."""
    return _OpenStatement(builder.clauses)


__all__ = [
    "Statement",
    "UnionStatement",
    "union",
]

"""
Subquery expressions.

A subquery expression runs a query of its own. The body reads the enclosing scope without
a scope clause, which is the difference from a ``CALL`` subquery. The body must be a
non-writing query, and the names it binds stay inside the expression: the outer query
never sees them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final, TypeVar

from cypher_dsl.ast import AstNode
from cypher_dsl.clauses.call import ProcedureCallClause, SubqueryCallClause
from cypher_dsl.clauses.write import CreateClause, DeleteClause, MergeClause, RemoveClause, SetClause
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.base import Expression
from cypher_dsl.expressions.operators import Condition
from cypher_dsl.patterns.nodes import PatternElement
from cypher_dsl.statements.composition import Statement, UnionStatement

if TYPE_CHECKING:
    from cypher_dsl.statements.builder import StatementBuilder

_WRITE_CLAUSE_TYPES: Final = (CreateClause, DeleteClause, MergeClause, RemoveClause, SetClause)


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class SubqueryExpression(Expression):
    """
    Base for the subquery expressions.

    The subclass states the keyword the expression renders with. The body reads the
    enclosing scope without a scope clause, must be a non-writing query, and the names
    it binds are not visible outside the expression. A body may end without a final
    ``RETURN``, which a standalone statement may not, so the factory functions
    finalise builders through the open-body route.

    Attributes:
        subquery: The finalised statement or union the expression evaluates.
    """

    keyword: ClassVar[str] = ""

    subquery: Statement | UnionStatement

    def __post_init__(self) -> None:
        """
        Reject a body the expression cannot hold.

        Raises:
            DslError: If the expression is built without a keyword, the body is not a
                finalised statement or union, or the body changes the graph directly or
                through a nested ``CALL`` body.
        """
        if not self.keyword:
            raise DslError(
                "A subquery expression subclass must state its keyword, "
                "for example through exists(), count_subquery() or collect_subquery()."
            )
        if not isinstance(self.subquery, (Statement, UnionStatement)):
            raise DslError(f"{self.keyword} needs a finalised statement or union, not {type(self.subquery).__name__}.")
        _reject_writing_body(self.subquery, self.keyword)

    def children(self) -> tuple[AstNode, ...]:
        """Expose the body as the only child."""
        return (self.subquery,)

    def local_names(self) -> tuple[str, ...]:
        """Return every name the body binds anywhere inside itself."""
        return _body_bound_names(self.subquery)


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class ExistsExpression(SubqueryExpression, Condition):
    """
    Test whether a non-writing subquery produces at least one row.

    The value is a predicate, so the expression filters in ``WHERE``, projects in
    ``RETURN`` and combines with ``&``, ``|`` and ``~``. The body reads the enclosing
    scope without a scope clause, and the names it binds are not visible outside the
    expression.

    Attributes:
        subquery: The finalised statement or union the expression tests.
    """

    keyword: ClassVar[str] = "EXISTS"


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class CountExpression(SubqueryExpression):
    """
    Count the rows a non-writing subquery produces.

    The body reads the enclosing scope without a scope clause, and the names it binds
    are not visible outside the expression. A final ``RETURN`` is optional and its
    columns are discarded.

    Attributes:
        subquery: The finalised statement or union the expression counts.
    """

    keyword: ClassVar[str] = "COUNT"


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class CollectExpression(SubqueryExpression):
    """
    Collect the single column a non-writing subquery returns into a list.

    The value is a list with one element per body row. The body reads the enclosing
    scope without a scope clause, and the names it binds are not visible outside the
    expression. Every branch must end in a ``RETURN`` projecting exactly one column,
    so a body without one is rejected here rather than by the server.

    Attributes:
        subquery: The finalised statement or union the expression collects.
    """

    keyword: ClassVar[str] = "COLLECT"

    def __post_init__(self) -> None:
        """
        Reject a body the expression cannot hold.

        Raises:
            DslError: If the body fails the shared subquery-expression checks, or a
                branch does not end in a ``RETURN`` projecting exactly one named
                column.
        """
        # Explicit super: the slots dataclass replaces the class, so the zero-argument form
        # resolves the pre-replacement class and raises TypeError.
        super(CollectExpression, self).__post_init__()
        from cypher_dsl.clauses.projection import ReturnClause
        from cypher_dsl.expressions.functions import Asterisk
        from cypher_dsl.statements.composition import _branches

        for branch in _branches(self.subquery):
            final = branch.clauses[-1]
            if not isinstance(final, ReturnClause):
                raise DslError(f"COLLECT takes a body that ends in RETURN, not {type(final).__name__}.")
            if len(final.expressions) != 1:
                raise DslError(f"COLLECT takes a RETURN with exactly one column, not {len(final.expressions)}.")
            if isinstance(final.expressions[0], Asterisk):
                raise DslError("COLLECT takes a RETURN with one named column, not RETURN *.")


TSubquery = TypeVar("TSubquery", bound=SubqueryExpression)


def _subquery_expression(
    kind: type[TSubquery],
    keyword: str,
    body: Statement | UnionStatement | StatementBuilder | PatternElement,
) -> TSubquery:
    """
    Finalise a body for one subquery expression kind.

    Args:
        kind: The expression class to build.
        keyword: The keyword the diagnostics name.
        body: A finalised statement or union, a builder, or a pattern element. A builder
            is finalised through the open-body route, so a body may end without a final
            ``RETURN`` and an incomplete body cannot reach a renderer. A pattern element
            becomes a body whose only clause is ``MATCH``, so the rendered text names
            the ``MATCH`` keyword.

    Returns:
        The subquery expression holding the finalised body.

    Raises:
        DslError: If the input is none of the accepted kinds.
    """
    from cypher_dsl.clauses.match import match
    from cypher_dsl.statements.builder import StatementBuilder
    from cypher_dsl.statements.composition import _open_statement

    if isinstance(body, PatternElement):
        return kind(_open_statement(match(body)))
    if isinstance(body, (Statement, UnionStatement)):
        return kind(body)
    if isinstance(body, StatementBuilder):
        return kind(_open_statement(body))
    raise DslError(
        f"{keyword} accepts statements, unions, statement builders and pattern elements, not {type(body).__name__}."
    )


def exists(body: Statement | UnionStatement | StatementBuilder | PatternElement) -> ExistsExpression:
    """
    Build ``EXISTS { ... }`` from a subquery body.

    The body reads the enclosing scope without a scope clause, unlike a ``CALL``
    subquery. It must be a non-writing query, and the names it binds are not visible
    outside the expression.

    Args:
        body: A finalised statement or union, a builder, or a pattern element. A pattern
            element becomes a ``MATCH``-only body, so the rendered text names the
            ``MATCH`` keyword.

    Returns:
        The existential subquery expression.

    Raises:
        DslError: If the input is none of the accepted kinds, or the body changes the
            graph directly or through a nested ``CALL`` body.
    """
    return _subquery_expression(ExistsExpression, "EXISTS", body)


def count_subquery(
    body: Statement | UnionStatement | StatementBuilder | PatternElement,
) -> CountExpression:
    """
    Build ``COUNT { ... }`` from a subquery body.

    The value is the number of rows the body produces. The body reads the enclosing
    scope without a scope clause, must be a non-writing query, and a final ``RETURN``
    is optional: its columns are discarded. The names the body binds are not visible
    outside the expression.

    Args:
        body: A finalised statement or union, a builder, or a pattern element. A pattern
            element becomes a ``MATCH``-only body, so the rendered text names the
            ``MATCH`` keyword.

    Returns:
        The counting subquery expression.

    Raises:
        DslError: If the input is none of the accepted kinds, or the body changes the
            graph directly or through a nested ``CALL`` body.
    """
    return _subquery_expression(CountExpression, "COUNT", body)


def collect_subquery(
    body: Statement | UnionStatement | StatementBuilder | PatternElement,
) -> CollectExpression:
    """
    Build ``COLLECT { ... }`` from a subquery body.

    The value is a list with one element per body row. The body reads the enclosing
    scope without a scope clause, must be a non-writing query, and every branch must
    end in a ``RETURN`` projecting exactly one column. The names the body binds are
    not visible outside the expression.

    Args:
        body: A finalised statement or union, a builder, or a pattern element. A
            pattern element becomes a ``MATCH``-only body and then fails the
            mandatory-``RETURN`` check.

    Returns:
        The collecting subquery expression.

    Raises:
        DslError: If the input is none of the accepted kinds, the body changes the
            graph directly or through a nested ``CALL`` body, or a branch does not end
            in a ``RETURN`` projecting exactly one named column.
    """
    return _subquery_expression(CollectExpression, "COLLECT", body)


def _reject_writing_body(subquery: Statement | UnionStatement, keyword: str) -> None:
    """
    Reject a body that changes the graph, directly or through a nested call.

    Raises:
        DslError: If the body holds a write clause, a nested ``CALL`` body does, or a
            nested call runs ``IN TRANSACTIONS``. A subquery expression takes a
            non-writing query.
    """
    from cypher_dsl.statements.composition import _branches

    statements = _branches(subquery)
    for statement in statements:
        for clause in statement.clauses:
            if isinstance(clause, _WRITE_CLAUSE_TYPES):
                raise DslError(f"{keyword} takes a non-writing subquery, not {type(clause).__name__}.")
            if isinstance(clause, SubqueryCallClause):
                if clause.in_transactions:
                    raise DslError(f"{keyword} takes a non-writing subquery, not one in inner transactions.")
                _reject_writing_body(clause.subquery, keyword)


def _body_bound_names(subquery: Statement | UnionStatement) -> tuple[str, ...]:
    """
    Return every name the body binds at any point inside itself.

    The union of all bindings, not the final visible set, because a name an inner ``WITH``
    discards is still a binding of this subtree and must not read as a free reference to
    an enclosing name. A trusted raw projection inside a nested ``CALL`` body can hide
    that call's output names; such a name may then read as free. That is the accepted
    cost of staying structural rather than frame-derived here.
    """
    from cypher_dsl.clauses.match import MatchClause
    from cypher_dsl.clauses.projection import ProjectionClause
    from cypher_dsl.clauses.unwind import UnwindClause
    from cypher_dsl.expressions.values import AliasedExpression, Variable
    from cypher_dsl.statements.composition import _branches
    from cypher_dsl.statements.frames import ScopeFrame
    from cypher_dsl.statements.rules.patterns import pattern_bindings
    from cypher_dsl.statements.rules.procedures import _yielded_bindings
    from cypher_dsl.statements.rules.subqueries import output_scope

    names: dict[str, None] = {}
    statements = _branches(subquery)
    for statement in statements:
        for clause in statement.clauses:
            if isinstance(clause, MatchClause):
                for bound in pattern_bindings(clause.patterns):
                    names.setdefault(bound, None)
            elif isinstance(clause, UnwindClause):
                names.setdefault(clause.variable.symbol.value, None)
            elif isinstance(clause, ProjectionClause):
                for expression in clause.expressions:
                    if isinstance(expression, AliasedExpression):
                        names.setdefault(expression.alias_name.value, None)
                    elif isinstance(expression, Variable):
                        names.setdefault(expression.symbol.value, None)
            elif isinstance(clause, ProcedureCallClause):
                for binding in _yielded_bindings(clause):
                    names.setdefault(binding, None)
            elif isinstance(clause, SubqueryCallClause):
                output = output_scope(clause.subquery, ScopeFrame())
                for bound in output.names or ():
                    names.setdefault(bound, None)
    return tuple(names)


__all__ = [
    "CollectExpression",
    "CountExpression",
    "ExistsExpression",
    "SubqueryExpression",
    "collect_subquery",
    "count_subquery",
    "exists",
]

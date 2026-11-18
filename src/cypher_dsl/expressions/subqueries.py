"""
The ``EXISTS`` subquery expression.

An existential subquery reads the enclosing scope without a scope clause, which is the
difference from a ``CALL`` subquery. The body must be a non-writing query, and the names
it binds stay inside the expression: the outer query never sees them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from cypher_dsl.ast import AstNode
from cypher_dsl.clauses.call import ProcedureCallClause, SubqueryCallClause
from cypher_dsl.clauses.write import CreateClause, DeleteClause, MergeClause, RemoveClause, SetClause
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.operators import Condition
from cypher_dsl.patterns.nodes import PatternElement
from cypher_dsl.statements.composition import Statement, UnionStatement

if TYPE_CHECKING:
    from cypher_dsl.statements.builder import StatementBuilder

_WRITE_CLAUSE_TYPES: Final = (CreateClause, DeleteClause, MergeClause, RemoveClause, SetClause)


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class ExistsExpression(Condition):
    """
    Test whether a non-writing subquery produces at least one row.

    The value is a predicate, so the expression filters in ``WHERE``, projects in
    ``RETURN`` and combines with ``&``, ``|`` and ``~``. The body reads the enclosing
    scope without a scope clause, and the names it binds are not visible outside the
    expression. The body may end without a final ``RETURN``, which a standalone statement
    may not, so :func:`exists` finalises builders through the open-body route.

    Attributes:
        subquery: The finalised statement or union the expression tests.
    """

    subquery: Statement | UnionStatement

    def __post_init__(self) -> None:
        """
        Reject a body the expression cannot hold.

        Raises:
            DslError: If the body is not a finalised statement or union, or changes the
                graph directly or through a nested ``CALL`` body.
        """
        if not isinstance(self.subquery, (Statement, UnionStatement)):
            raise DslError(f"EXISTS needs a finalised statement or union, not {type(self.subquery).__name__}.")
        _reject_writing_body(self.subquery)

    def children(self) -> tuple[AstNode, ...]:
        """Expose the body as the only child."""
        return (self.subquery,)

    def local_names(self) -> tuple[str, ...]:
        """Return every name the body binds anywhere inside itself."""
        return _body_bound_names(self.subquery)


def exists(body: Statement | UnionStatement | StatementBuilder | PatternElement) -> ExistsExpression:
    """
    Build ``EXISTS { ... }`` from a subquery body.

    The body reads the enclosing scope without a scope clause, unlike a ``CALL``
    subquery. It must be a non-writing query, and the names it binds are not visible
    outside the expression.

    Args:
        body: A finalised statement, union or builder, or a pattern element. A builder is
            finalised through the open-body route, so a body may end without a final
            ``RETURN`` and an incomplete body cannot reach a renderer. A pattern element
            becomes a body whose only clause is ``MATCH``, so the rendered text names the
            ``MATCH`` keyword.

    Returns:
        The existential subquery expression, usable wherever a condition is.

    Raises:
        DslError: If the input is none of the accepted kinds, or the body changes the
            graph directly or through a nested ``CALL`` body.
    """
    from cypher_dsl.clauses.match import match
    from cypher_dsl.statements.builder import StatementBuilder
    from cypher_dsl.statements.composition import _open_statement

    if isinstance(body, PatternElement):
        return ExistsExpression(_open_statement(match(body)))
    if isinstance(body, (Statement, UnionStatement)):
        return ExistsExpression(body)
    if isinstance(body, StatementBuilder):
        return ExistsExpression(_open_statement(body))
    raise DslError(
        f"EXISTS accepts statements, unions, statement builders and pattern elements, not {type(body).__name__}."
    )


def _reject_writing_body(subquery: Statement | UnionStatement) -> None:
    """
    Reject a body that changes the graph, directly or through a nested call.

    Raises:
        DslError: If the body holds a write clause, a nested ``CALL`` body does, or a
            nested call runs ``IN TRANSACTIONS``. ``EXISTS`` takes a non-writing query.
    """
    from cypher_dsl.statements.composition import _branches

    statements = _branches(subquery)
    for statement in statements:
        for clause in statement.clauses:
            if isinstance(clause, _WRITE_CLAUSE_TYPES):
                raise DslError(f"EXISTS takes a non-writing subquery, not {type(clause).__name__}.")
            if isinstance(clause, SubqueryCallClause):
                if clause.in_transactions:
                    raise DslError("EXISTS takes a non-writing subquery, not one in inner transactions.")
                _reject_writing_body(clause.subquery)


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


__all__ = ["ExistsExpression", "exists"]

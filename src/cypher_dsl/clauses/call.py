"""
The ``CALL`` subquery clause.

A subquery call runs a finalised statement once per incoming row in its own scope. The
outer variables enter the body only through the variable scope clause the call renders,
and the names the body's final ``RETURN`` projects become available to the clauses after
the call. The clause stores names, not rendered text, so identifier quoting stays a
rendering decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cypher_dsl.ast import AstNode, _require_tuple
from cypher_dsl.clauses.base import Clause
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.base import Expression, ExpressionInput, require_operand
from cypher_dsl.expressions.values import Literal, SymbolicName, Variable, validate_name
from cypher_dsl.statements.composition import Statement, UnionStatement

if TYPE_CHECKING:
    from cypher_dsl.statements.builder import StatementBuilder


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class SubqueryCallClause(Clause):
    """
    Run a finalised statement once per incoming row in its own scope.

    The scope clause states the outer variables the body receives. The names the body's
    final ``RETURN`` projects become available to the clauses after the call. A body
    without a ``RETURN`` is a unit subquery: it changes the graph without changing the
    number of rows.

    Attributes:
        subquery: The finalised statement or union the call runs.
        imports: Variables the scope clause passes from the outer query into the body.
            They are declarations, so they are not children.
        import_all: Render ``(*)`` and treat every outer variable as imported.
        optional: Render ``OPTIONAL CALL`` so rows without subquery output survive with
            ``null`` bindings.
        in_transactions: Run the body in separate inner transactions.
        of_rows: Input rows per inner transaction, rendered as ``OF ... ROWS``. It
            requires ``in_transactions``.
    """

    subquery: Statement | UnionStatement
    imports: tuple[Variable, ...] = ()
    import_all: bool = False
    optional: bool = False
    in_transactions: bool = False
    of_rows: Expression | None = None

    def __post_init__(self) -> None:
        """
        Reject a body, an import list or a transaction modifier the clause cannot hold.

        Raises:
            DslError: If the body is not a finalised statement or union, a collection is
                not a tuple, an import is not a variable, named imports are combined
                with ``import_all``, a flag is not a boolean, or the row count is not an
                expression that can denote a positive integer.
            InvalidIdentifierError: If an import name cannot be an identifier.
        """
        if not isinstance(self.subquery, (Statement, UnionStatement)):
            raise DslError(f"CALL needs a finalised statement or union, not {type(self.subquery).__name__}.")
        _require_tuple(self.imports, "CALL imports")
        for field in ("import_all", "optional", "in_transactions"):
            if not isinstance(getattr(self, field), bool):
                raise DslError(f"{field} is a boolean choice, not {type(getattr(self, field)).__name__}.")
        if self.import_all and self.imports:
            raise DslError("CALL takes either named imports or (*), not both.")
        for variable in self.imports:
            if not isinstance(variable, Variable):
                raise DslError(f"CALL imports need variables, not {type(variable).__name__}.")
            validate_name(variable.symbol.value)
        self._validate_of_rows()

    def _validate_of_rows(self) -> None:
        """Reject a row count that cannot denote a positive integer."""
        if self.of_rows is None:
            return
        if not self.in_transactions:
            raise DslError("OF ... ROWS belongs to IN TRANSACTIONS. Pass in_transactions=True with of_rows.")
        if not isinstance(self.of_rows, Expression):
            raise DslError(f"OF ... ROWS needs an expression, not {type(self.of_rows).__name__}.")
        require_operand(self.of_rows)
        if not isinstance(self.of_rows, Literal):
            return
        rows = self.of_rows.value
        if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1:
            raise DslError(
                f"OF ... ROWS requires a positive integer literal, not {rows!r}. Bind a runtime value with param()."
            )

    def children(self) -> tuple[AstNode, ...]:
        """Expose the body and the row-count expression in rendered order."""
        return (self.subquery,) if self.of_rows is None else (self.subquery, self.of_rows)


def _coerce_import(item: object) -> Variable:
    """
    Turn one import input into a variable.

    Args:
        item: A variable or a bare variable name.

    Returns:
        The variable the scope clause renders.

    Raises:
        DslError: If the input is neither a variable nor a string.
        InvalidIdentifierError: If a string cannot be an identifier.
    """
    if isinstance(item, Variable):
        return item
    if isinstance(item, str):
        validate_name(item)
        return Variable(SymbolicName(item))
    raise DslError(f"CALL imports need a variable or a variable name, not {type(item).__name__}.")


def _finalise_subquery(value: object) -> Statement | UnionStatement:
    """
    Finalise one subquery input.

    Args:
        value: A statement, a union or a statement builder.

    Returns:
        The finalised body the clause can hold.

    Raises:
        DslError: If the input is none of the accepted kinds.
    """
    from cypher_dsl.statements.builder import StatementBuilder

    if isinstance(value, StatementBuilder):
        return value.build()
    if isinstance(value, (Statement, UnionStatement)):
        return value
    raise DslError(f"CALL accepts statements, unions and statement builders, not {type(value).__name__}.")


def call(
    subquery: Statement | UnionStatement | StatementBuilder,
    imports: tuple[str | Variable, ...] = (),
    import_all: bool = False,
    in_transactions: bool | ExpressionInput = False,
) -> StatementBuilder:
    """
    Start a statement whose only clause calls a subquery.

    The call renders the 5.23+ variable scope clause, so a body sees outer variables
    only through ``imports`` or ``import_all``. A body that ends in ``RETURN`` makes its
    returned names available to the clauses after the call.

    Args:
        subquery: Finalised statement, union or builder. A builder is finalised through
            ``build``, so an incomplete body cannot reach a renderer.
        imports: Outer variables the scope clause passes into the body. A bare string is
            a variable name.
        import_all: Render ``(*)`` and pass every outer variable into the body.
        in_transactions: Run the body in separate inner transactions. ``True`` renders
            the bare modifier. A positive integer literal, parameter or expression
            renders ``OF ... ROWS``.

    Returns:
        A new builder whose only clause is the ``CALL``.

    Raises:
        DslError: If the body is not finalisable, an import is not a variable name,
            named imports and ``import_all`` are combined, or the row count is invalid.
    """
    from cypher_dsl.statements.builder import StatementBuilder

    return StatementBuilder().call(subquery, imports=imports, import_all=import_all, in_transactions=in_transactions)


def optional_call(
    subquery: Statement | UnionStatement | StatementBuilder,
    imports: tuple[str | Variable, ...] = (),
    import_all: bool = False,
    in_transactions: bool | ExpressionInput = False,
) -> StatementBuilder:
    """
    Start a statement whose only clause optionally calls a subquery.

    ``OPTIONAL CALL`` keeps an outer row alive with ``null`` bindings when the body
    produces no rows for it, the same way ``OPTIONAL MATCH`` does.

    Args:
        subquery: Finalised statement, union or builder. A builder is finalised through
            ``build``.
        imports: Outer variables the scope clause passes into the body.
        import_all: Render ``(*)`` and pass every outer variable into the body.
        in_transactions: Run the body in separate inner transactions. ``True`` renders
            the bare modifier. A positive integer literal, parameter or expression
            renders ``OF ... ROWS``.

    Returns:
        A new builder whose only clause is the ``OPTIONAL CALL``.

    Raises:
        DslError: If the body is not finalisable, an import is not a variable name,
            named imports and ``import_all`` are combined, or the row count is invalid.
    """
    from cypher_dsl.statements.builder import StatementBuilder

    return StatementBuilder().optional_call(
        subquery, imports=imports, import_all=import_all, in_transactions=in_transactions
    )


__all__ = ["SubqueryCallClause", "call", "optional_call"]

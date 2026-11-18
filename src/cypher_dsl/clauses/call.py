"""
The ``CALL`` clause in its subquery and procedure-call forms.

The two forms are the subquery call, which runs a statement in its own scope, and the
procedure call, which invokes a stored procedure and binds the columns it yields. A
procedure call may filter its yielded rows with a predicate.

A subquery call runs a finalised statement once per incoming row in its own scope. The
outer variables enter the body only through the variable scope clause the call renders,
and the names the body's final ``RETURN`` projects become available to the clauses after
the call. The clause stores names, not rendered text, so identifier quoting stays a
rendering decision.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from cypher_dsl.ast import AstNode, _require_tuple
from cypher_dsl.clauses.base import Clause
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.base import Expression, ExpressionInput, require_operand
from cypher_dsl.expressions.operators import Condition
from cypher_dsl.expressions.values import AliasedExpression, Literal, SymbolicName, Variable, validate_name
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


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class ProcedureCallClause(Clause):
    """
    Invoke a stored procedure and bind the columns it yields.

    A call without ``OPTIONAL`` keeps only the rows the procedure produces. ``OPTIONAL``
    keeps an incoming row alive with ``null`` bindings when the procedure produces no row
    for it, the same way ``OPTIONAL MATCH`` does. A predicate filters the yielded rows, so
    it is meaningful only after at least one yield item.

    Attributes:
        name: Procedure name segments in call order. ``db.labels`` is two segments.
        arguments: Argument expressions, in call order.
        optional: Render ``OPTIONAL CALL`` so rows without procedure output survive with
            ``null`` bindings.
        yields: Columns the call binds, each a variable or a variable under one alias. An
            empty tuple binds nothing.
        predicate: Filter applied to the yielded rows, rendered after ``YIELD``. It
            requires at least one yield item.
    """

    name: tuple[str, ...]
    arguments: tuple[Expression, ...]
    optional: bool
    yields: tuple[Variable | AliasedExpression, ...] = ()
    predicate: Expression | None = None

    def __post_init__(self) -> None:
        """
        Reject a name, argument, yield list or predicate the clause cannot hold.

        Raises:
            DslError: If the name is not a non-empty tuple of strings, the flag is not a
                boolean, a collection is not a tuple, an argument or predicate is not an
                expression or is an alias, a yield item is not a variable or an alias of a
                variable, two yield items bind the same name, or a predicate is set
                without yield items.
            InvalidIdentifierError: If a name segment cannot be an identifier.
        """
        if not isinstance(self.name, tuple) or any(not isinstance(segment, str) for segment in self.name):
            raise DslError(
                f"CALL needs a procedure name as a tuple of string segments, not {type(self.name).__name__}."
            )
        if not self.name:
            raise DslError("CALL needs a procedure name with at least one segment.")
        for segment in self.name:
            validate_name(segment)
        if not isinstance(self.optional, bool):
            raise DslError(f"optional is a boolean choice, not {type(self.optional).__name__}.")
        _require_tuple(self.arguments, "CALL arguments")
        _require_tuple(self.yields, "CALL yields")
        for argument in self.arguments:
            if not isinstance(argument, Expression):
                raise DslError(f"CALL arguments need expressions, not {type(argument).__name__}.")
            require_operand(argument)
        seen: set[str] = set()
        for item in self.yields:
            if isinstance(item, Variable):
                binding = item.symbol.value
            elif isinstance(item, AliasedExpression):
                if not isinstance(item.expression, Variable):
                    raise DslError(
                        f"CALL YIELD aliases a variable, not {type(item.expression).__name__}. Alias a plain name()."
                    )
                binding = item.alias_name.value
            else:
                raise DslError(f"CALL YIELD takes a variable or an aliased variable, not {type(item).__name__}.")
            if binding in seen:
                raise DslError(f"CALL YIELD already binds {binding!r}. Give each yielded column a distinct name.")
            seen.add(binding)
        if self.predicate is None:
            return
        if not self.yields:
            raise DslError("A CALL predicate filters YIELD output. Pass the yield items before the predicate.")
        if not isinstance(self.predicate, Expression):
            raise DslError(f"CALL predicate needs an expression, not {type(self.predicate).__name__}.")
        require_operand(self.predicate)

    def children(self) -> tuple[AstNode, ...]:
        """Expose the arguments, the yield items and the predicate in rendered order."""
        renderable: tuple[AstNode, ...] = (*self.arguments, *self.yields)
        return renderable if self.predicate is None else (*renderable, self.predicate)

    def with_where(self, predicate: Condition) -> ProcedureCallClause:
        """
        Return a copy whose single attached filter also requires ``predicate``.

        Consecutive filters join with ``AND`` because the call has one filter position
        after ``YIELD``. Returning a copy keeps every other clause value shareable.

        Args:
            predicate: Additional condition.

        Returns:
            A new clause with one combined filter.
        """
        combined = predicate if self.predicate is None else self.predicate & predicate
        return replace(self, predicate=combined)


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


def call_procedure(procedure_name: str, *arguments: ExpressionInput) -> StatementBuilder:
    """
    Start a statement whose only clause calls a stored procedure.

    The name is one dot-qualified string, split on dots the same way :func:`fn` splits a
    function name. The call binds nothing without ``YIELD`` items, and a call without
    them is finalisable without a ``RETURN``.

    Args:
        procedure_name: Dot-qualified procedure name, such as ``db.labels``.
        arguments: Argument expressions or literal values. A bare string is a literal,
            not a name.

    Returns:
        A new builder whose only clause is the ``CALL``.

    Raises:
        DslError: If an argument cannot be an expression or is an alias.
        InvalidIdentifierError: If a name segment cannot be an identifier.
    """
    from cypher_dsl.statements.builder import StatementBuilder

    return StatementBuilder().call_procedure(procedure_name, *arguments)


def optional_call_procedure(procedure_name: str, *arguments: ExpressionInput) -> StatementBuilder:
    """
    Start a statement whose only clause optionally calls a stored procedure.

    ``OPTIONAL CALL`` keeps an incoming row alive with ``null`` bindings when the
    procedure produces no row for it, the same way ``OPTIONAL MATCH`` does.

    Args:
        procedure_name: Dot-qualified procedure name, such as ``db.labels``.
        arguments: Argument expressions or literal values. A bare string is a literal,
            not a name.

    Returns:
        A new builder whose only clause is the ``OPTIONAL CALL``.

    Raises:
        DslError: If an argument cannot be an expression or is an alias.
        InvalidIdentifierError: If a name segment cannot be an identifier.
    """
    from cypher_dsl.statements.builder import StatementBuilder

    return StatementBuilder().optional_call_procedure(procedure_name, *arguments)


__all__ = [
    "ProcedureCallClause",
    "SubqueryCallClause",
    "call",
    "call_procedure",
    "optional_call",
    "optional_call_procedure",
]

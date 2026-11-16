"""
The ``UNWIND`` clause and its row-producing binding.

``UNWIND`` is a reading clause: it adds one variable per row and binds it for the clauses
that follow. Filtering is not part of the clause, so a caller who needs a predicate adds
``WITH`` first; attaching ``WHERE`` directly would render syntax the server rejects.

The clause owns the variable as a name, not as rendered text, so identifier quoting stays
a rendering decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cypher_dsl.clauses.base import Clause
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.base import Expression, ExpressionInput, require_operand
from cypher_dsl.expressions.values import Variable, validate_name
from cypher_dsl.syntax import AstNode

if TYPE_CHECKING:
    from cypher_dsl.statements.builder import StatementBuilder


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class UnwindClause(Clause):
    """
    Turn each element of a collection into one row.

    Attributes:
        values: Expression whose runtime value is iterated. It is language syntax, not a
            Python list, so a parameter or property read stays a parameter or read.
        variable: Variable bound to the current element. It must be a variable because
            the grammar has no other form in that position.
    """

    values: Expression
    variable: Variable

    def __post_init__(self) -> None:
        """
        Reject a non-expression source or a target that is not a variable.

        Raises:
            DslError: If the value is not an expression, or the target is not a variable.
            InvalidIdentifierError: If the bound name cannot be an identifier.
        """
        if not isinstance(self.values, Expression):
            raise DslError(f"UNWIND needs an expression to unwind, not {type(self.values).__name__}.")
        require_operand(self.values)
        if not isinstance(self.variable, Variable):
            raise DslError(
                f"UNWIND needs a variable target, not {type(self.variable).__name__}. "
                "Use name() for the variable each row is bound to."
            )
        validate_name(self.variable.symbol.value)

    def children(self) -> tuple[AstNode, ...]:
        """Expose the unwound expression; the variable is a declaration, not a child."""
        return (self.values,)


def unwind(values: ExpressionInput, variable: Variable) -> StatementBuilder:
    """
    Start a statement with an ``UNWIND`` clause.

    Args:
        values: Collection expression or literal data. A Python list becomes a list
            literal, while ``param()`` keeps the rows out of the query text.
        variable: Variable bound to the current element.

    Returns:
        A new builder whose only clause is ``UNWIND``. It is not finalisable until a
        ``RETURN`` or a write clause follows.

    Raises:
        DslError: If the target is not a variable or the value cannot become an
            expression.
    """
    from cypher_dsl.statements.builder import StatementBuilder

    return StatementBuilder().unwind(values, variable)


__all__ = ["UnwindClause", "unwind"]

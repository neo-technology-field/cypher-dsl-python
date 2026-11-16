"""
Static property access and dynamic subscript expressions.

A property key is a name and a subscript key is syntax. Keeping them as separate node
types stops a string from being interpolated into query text and lets the renderer
quote a static key without quoting an expression.
"""

from __future__ import annotations

from dataclasses import dataclass

from cypher_dsl.expressions.base import Expression, require_operand
from cypher_dsl.expressions.values import SymbolicName
from cypher_dsl.syntax import AstNode


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class Property(Expression):
    """
    A statically named property of another expression.

    Attributes:
        expression: Base expression the property is read from.
        key: Property name, quoted as an identifier at render time.
    """

    expression: Expression
    key: SymbolicName

    def __post_init__(self) -> None:
        """Reject an alias as a property base."""
        require_operand(self.expression)

    def children(self) -> tuple[AstNode, ...]:
        """Expose the base expression."""
        return (self.expression,)


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class SubscriptExpression(Expression):
    """
    A value selected by an expression inside brackets.

    Attributes:
        expression: Base expression the value is read from.
        key: Index or key expression, kept as syntax so parameters stay parameters.
    """

    expression: Expression
    key: Expression

    def __post_init__(self) -> None:
        """Reject aliases as the base or the key."""
        require_operand(self.expression)
        require_operand(self.key)

    def children(self) -> tuple[AstNode, ...]:
        """Expose the base and the key in rendered order."""
        return (self.expression, self.key)


__all__ = ["Property", "SubscriptExpression"]

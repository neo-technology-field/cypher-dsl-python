"""
Predicates, arithmetic and boolean expressions.

Operators are built here rather than in the syntax nodes so that every path applies
the same coercion and operator validation. The binding strength of each node is
declared next to its operator, which lets the renderer add parentheses without
guessing from the rendered text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from cypher_dsl.ast import AstNode
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.base import (
    Expression,
    ExpressionInput,
    Precedence,
    coerce_expression,
    require_operand,
)

_ARITHMETIC_OPERATORS: Final = frozenset({"+", "-", "*", "/", "%"})
_BOOLEAN_OPERATORS: Final = frozenset({"AND", "OR"})
_NULL_OPERATORS: Final = frozenset({"IS NULL", "IS NOT NULL"})
_COMPARISON_OPERATORS: Final = frozenset({"=", "<>", "<", "<=", ">", ">=", "IN"}) | _NULL_OPERATORS
_UNARY_OPERATORS: Final = frozenset({"NOT", "-", "+"})


class Condition(Expression):
    """
    Base for expressions whose value is a predicate.

    The class is a typing and traversal seam, not a claim about server-side types.
    :func:`condition` wraps an expression the caller knows to be boolean without
    pretending the library can infer that.
    """

    __slots__ = ()


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class Comparison(Condition):
    """
    A binary comparison or an ``IS NULL`` test.

    Attributes:
        operator: One of the comparison, membership or null operators.
        left: Expression on the left of the operator.
        right: Expression on the right, or ``None`` for a postfix null test.
    """

    operator: str
    left: Expression
    right: Expression | None = None

    def __post_init__(self) -> None:
        """Reject an unknown operator or a null test with a right operand."""
        if self.operator not in _COMPARISON_OPERATORS:
            raise DslError(f"{self.operator!r} is not a supported comparison operator.")
        require_operand(self.left)
        is_null_test = self.operator in _NULL_OPERATORS
        if self.right is None:
            if not is_null_test:
                raise DslError(f"{self.operator!r} needs a right operand.")
            return
        if is_null_test:
            raise DslError(f"{self.operator!r} does not take a right operand.")
        require_operand(self.right)

    @property
    def precedence(self) -> Precedence:
        """Return the comparison level, shared by equality and membership."""
        return Precedence.COMPARISON

    def children(self) -> tuple[AstNode, ...]:
        """Expose the operands in rendered order."""
        return (self.left,) if self.right is None else (self.left, self.right)


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class BinaryOperation(Expression):
    """
    Two operands joined by an arithmetic or boolean operator.

    Attributes:
        operator: Symbol or logical word between the operands.
        left: Operand on the left.
        right: Operand on the right.
    """

    operator: str
    left: Expression
    right: Expression

    def __post_init__(self) -> None:
        """Reject an operator that is neither arithmetic nor logical."""
        if self.operator not in _ARITHMETIC_OPERATORS | _BOOLEAN_OPERATORS:
            raise DslError(f"{self.operator!r} is not a supported binary operator.")
        require_operand(self.left)
        require_operand(self.right)

    @property
    def precedence(self) -> Precedence:
        """Return the binding strength implied by the operator."""
        if self.operator == "AND":
            return Precedence.AND
        if self.operator == "OR":
            return Precedence.OR
        if self.operator in {"+", "-"}:
            return Precedence.ADDITIVE
        return Precedence.MULTIPLICATIVE

    def children(self) -> tuple[AstNode, ...]:
        """Expose both operands in rendered order."""
        return (self.left, self.right)


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class UnaryOperation(Expression):
    """
    An operand preceded by unary arithmetic or ``NOT``.

    Attributes:
        operator: ``-``, ``+`` or ``NOT``.
        operand: Expression the operator applies to.
    """

    operator: str
    operand: Expression

    def __post_init__(self) -> None:
        """Reject an operator that is not a supported unary operator."""
        if self.operator not in _UNARY_OPERATORS:
            raise DslError(f"{self.operator!r} is not a supported unary operator.")
        require_operand(self.operand)

    @property
    def precedence(self) -> Precedence:
        """Place ``NOT`` below comparisons and unary arithmetic above them."""
        return Precedence.NOT if self.operator == "NOT" else Precedence.UNARY

    def children(self) -> tuple[AstNode, ...]:
        """Expose the operand."""
        return (self.operand,)


class _Negation(UnaryOperation, Condition):
    """A ``NOT`` operation, which is a predicate rather than a value."""

    __slots__ = ()


class _LogicalOperation(BinaryOperation, Condition):
    """An ``AND`` or ``OR`` operation, which is a predicate rather than a value."""

    __slots__ = ()


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class _ConditionOperand(Condition):
    """
    An explicitly boolean expression used as a predicate.

    The wrapper adds no syntax. It records that the caller vouched for the boolean
    value, keeping non-predicate expressions out of ``Condition`` positions.
    """

    operand: Expression

    def __post_init__(self) -> None:
        """Reject an alias, which cannot be an operand."""
        require_operand(self.operand)

    @property
    def precedence(self) -> Precedence:
        """Inherit the operand's binding strength, because the wrapper adds no text."""
        return self.operand.precedence

    def children(self) -> tuple[AstNode, ...]:
        """Expose the wrapped expression."""
        return (self.operand,)


def arithmetic_operation(operator: str, left: Expression, right: ExpressionInput) -> BinaryOperation:
    """
    Build an arithmetic operation from an operator and two operands.

    Args:
        operator: One of ``+``, ``-``, ``*``, ``/`` or ``%``.
        left: Left operand.
        right: Right operand or literal value.

    Returns:
        A binary arithmetic node.

    Raises:
        DslError: If the operator is not arithmetic or the operands are aliases.
        InvalidLiteralError: If the right operand cannot become a literal.
    """
    return BinaryOperation(operator, require_operand(left), coerce_expression(right))


def comparison_operation(operator: str, left: Expression, right: ExpressionInput) -> Comparison:
    """
    Build a comparison, membership test or null predicate.

    Args:
        operator: Comparison or membership operator, or a postfix null operator.
        left: Left operand, or the tested expression for a null operator.
        right: Right operand or literal value.

    Returns:
        A comparison predicate.

    Raises:
        DslError: If the operator and operands do not form a supported predicate.
    """
    if operator in _NULL_OPERATORS and right is None:
        return Comparison(operator, require_operand(left), None)
    return Comparison(operator, require_operand(left), coerce_expression(right))


def boolean_operation(operator: str, left: Expression, right: ExpressionInput) -> Condition:
    """
    Join two expressions with ``AND`` or ``OR``.

    Python's ``and`` and ``or`` cannot be overloaded, so this function is the only
    explicit entry point for a caller that does not use the operator syntax.

    Args:
        operator: ``AND`` or ``OR``, case-insensitive.
        left: Left expression.
        right: Right expression or literal value.

    Returns:
        A boolean predicate.

    Raises:
        DslError: If the operator is not a logical operator.
    """
    normalised = operator.strip().upper()
    if normalised not in _BOOLEAN_OPERATORS:
        raise DslError(f"{operator!r} is not a logical operator. Use AND or OR.")
    return _LogicalOperation(normalised, require_operand(left), coerce_expression(right))


def unary_operation(operator: str, operand: Expression) -> UnaryOperation:
    """
    Build a unary arithmetic operation.

    Args:
        operator: ``-`` or ``+``.
        operand: Expression the operator applies to.

    Returns:
        A unary arithmetic node.

    Raises:
        DslError: If the operator is not unary arithmetic or the operand is an alias.
    """
    if operator.strip().upper() == "NOT":
        raise DslError("Use ~ or unary_condition() to negate a condition.")
    return UnaryOperation(operator, require_operand(operand))


def unary_condition(operator: str, operand: Expression) -> Condition:
    """
    Negate a condition.

    Args:
        operator: Only ``NOT`` is accepted.
        operand: Expression to negate.

    Returns:
        A negation predicate.

    Raises:
        DslError: If the operator is not ``NOT`` or the operand is an alias.
    """
    if operator.strip().upper() != "NOT":
        raise DslError(f"{operator!r} is not a logical operator. Use NOT.")
    return _Negation("NOT", require_operand(operand))


def condition(value: ExpressionInput) -> Condition:
    """
    Treat an explicitly boolean expression as a predicate.

    No server-side type inference is attempted. The caller states that a parameter,
    property or function result is boolean, and the wrapper renders it unchanged.

    Args:
        value: Expression or literal value known to be boolean.

    Returns:
        The value itself when it is already a condition, otherwise a predicate
        wrapper around it.

    Raises:
        DslError: If the value is an alias.
    """
    expression = coerce_expression(value)
    if isinstance(expression, Condition):
        return expression
    return _ConditionOperand(expression)


def in_(value: ExpressionInput, collection: ExpressionInput) -> Condition:
    """
    Build a membership test.

    Args:
        value: Item to look up. A bare string is a literal value.
        collection: Collection expression or literal collection.

    Returns:
        A predicate rendering ``value IN collection``.
    """
    return Comparison("IN", coerce_expression(value), coerce_expression(collection))


__all__ = [
    "BinaryOperation",
    "Comparison",
    "Condition",
    "UnaryOperation",
    "arithmetic_operation",
    "boolean_operation",
    "comparison_operation",
    "condition",
    "in_",
    "unary_condition",
    "unary_operation",
]

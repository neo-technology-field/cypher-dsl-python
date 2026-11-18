"""
Expression contracts shared by values, predicates and functions.

The input aliases define the coercion boundary. A literal position accepts only data
that can become Cypher syntax, an expression position also accepts syntax nodes, and a
projection keeps the same shape but treats a bare string as a variable name.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from enum import IntEnum
from typing import TYPE_CHECKING, ClassVar, TypeAlias, Union, cast

from cypher_dsl.ast import AstNode
from cypher_dsl.errors import DslError

if TYPE_CHECKING:
    from cypher_dsl.expressions.operators import BinaryOperation, Comparison, Condition, UnaryOperation
    from cypher_dsl.expressions.values import AliasedExpression


class Precedence(IntEnum):
    """
    Binding strength of an expression, lowest first.

    The renderer uses one table instead of letting each node decide its own
    parentheses. Cypher's operator order is fixed, so a single ordered set keeps
    arithmetic, predicates and boolean grouping consistent.
    """

    OR = 0
    AND = 1
    NOT = 2
    COMPARISON = 3
    ADDITIVE = 4
    MULTIPLICATIVE = 5
    UNARY = 6
    ATOM = 7


class NamedExpression(ABC):
    """Provide an expression reference for a named syntax node."""

    __slots__ = ()

    @abstractmethod
    def as_expression(self) -> Expression:
        """Return the expression reference, rejecting anonymous syntax nodes."""
        ...


class Expression(AstNode):
    """
    Base for every node that can appear in an expression position.

    Expressions are syntax, not values. Truth testing raises immediately so that a
    chained Python comparison or a stray ``if expression`` fails instead of silently
    discarding part of the tree. Hashing is disabled as well: identity-based keys would
    make equal-looking trees collide unpredictably.
    """

    __slots__ = ()

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    @property
    def precedence(self) -> Precedence:
        """Return how tightly this expression binds in its parent."""
        return Precedence.ATOM

    def __bool__(self) -> bool:
        """Reject truth testing, which Python only supports by guessing a value."""
        raise TypeError(
            "Cypher expressions cannot be evaluated as booleans. Build a predicate with the DSL operators instead."
        )

    # noinspection method-overriding
    def __eq__(self, other: object) -> Condition:  # type: ignore[override]
        """
        Build an equality predicate, or a null test when ``other`` is ``None``.

        The object protocol promises ``bool``. Expression equality cannot promise it:
        comparing two expressions builds Cypher syntax, and Python truth testing of the
        result is rejected.
        """
        from cypher_dsl.expressions.operators import comparison_operation

        if other is None:
            return comparison_operation("IS NULL", self, None)
        return comparison_operation("=", self, cast(ExpressionInput, other))

    # noinspection method-overriding
    def __ne__(self, other: object) -> Condition:  # type: ignore[override]
        """Build an inequality predicate, or a negated null test for ``None``."""
        from cypher_dsl.expressions.operators import comparison_operation

        if other is None:
            return comparison_operation("IS NOT NULL", self, None)
        return comparison_operation("<>", self, cast(ExpressionInput, other))

    def __lt__(self, other: ExpressionInput) -> Comparison:
        """Build a less-than comparison."""
        from cypher_dsl.expressions.operators import comparison_operation

        return comparison_operation("<", self, other)

    def __le__(self, other: ExpressionInput) -> Comparison:
        """Build a less-than-or-equal comparison."""
        from cypher_dsl.expressions.operators import comparison_operation

        return comparison_operation("<=", self, other)

    def __gt__(self, other: ExpressionInput) -> Comparison:
        """Build a greater-than comparison."""
        from cypher_dsl.expressions.operators import comparison_operation

        return comparison_operation(">", self, other)

    def __ge__(self, other: ExpressionInput) -> Comparison:
        """Build a greater-than-or-equal comparison."""
        from cypher_dsl.expressions.operators import comparison_operation

        return comparison_operation(">=", self, other)

    def __add__(self, other: ExpressionInput) -> BinaryOperation:
        """Build an addition, which Cypher also uses for string concatenation."""
        from cypher_dsl.expressions.operators import arithmetic_operation

        return arithmetic_operation("+", self, other)

    def __radd__(self, other: ExpressionInput) -> BinaryOperation:
        """Build an addition with the other operand on the left."""
        from cypher_dsl.expressions.operators import arithmetic_operation

        return arithmetic_operation("+", coerce_expression(other), self)

    def __sub__(self, other: ExpressionInput) -> BinaryOperation:
        """Build a subtraction."""
        from cypher_dsl.expressions.operators import arithmetic_operation

        return arithmetic_operation("-", self, other)

    def __rsub__(self, other: ExpressionInput) -> BinaryOperation:
        """Build a subtraction with the other operand on the left."""
        from cypher_dsl.expressions.operators import arithmetic_operation

        return arithmetic_operation("-", coerce_expression(other), self)

    def __mul__(self, other: ExpressionInput) -> BinaryOperation:
        """Build a multiplication."""
        from cypher_dsl.expressions.operators import arithmetic_operation

        return arithmetic_operation("*", self, other)

    def __rmul__(self, other: ExpressionInput) -> BinaryOperation:
        """Build a multiplication with the other operand on the left."""
        from cypher_dsl.expressions.operators import arithmetic_operation

        return arithmetic_operation("*", coerce_expression(other), self)

    def __truediv__(self, other: ExpressionInput) -> BinaryOperation:
        """Build a division."""
        from cypher_dsl.expressions.operators import arithmetic_operation

        return arithmetic_operation("/", self, other)

    def __rtruediv__(self, other: ExpressionInput) -> BinaryOperation:
        """Build a division with the other operand on the left."""
        from cypher_dsl.expressions.operators import arithmetic_operation

        return arithmetic_operation("/", coerce_expression(other), self)

    def __mod__(self, other: ExpressionInput) -> BinaryOperation:
        """Build a modulo division."""
        from cypher_dsl.expressions.operators import arithmetic_operation

        return arithmetic_operation("%", self, other)

    def __rmod__(self, other: ExpressionInput) -> BinaryOperation:
        """Build a modulo division with the other operand on the left."""
        from cypher_dsl.expressions.operators import arithmetic_operation

        return arithmetic_operation("%", coerce_expression(other), self)

    def __neg__(self) -> UnaryOperation:
        """Build a unary minus."""
        from cypher_dsl.expressions.operators import unary_operation

        return unary_operation("-", self)

    def __pos__(self) -> UnaryOperation:
        """Build a unary plus."""
        from cypher_dsl.expressions.operators import unary_operation

        return unary_operation("+", self)

    def __and__(self, other: Condition) -> Condition:
        """Build a conjunction. Python's ``and`` cannot be overloaded."""
        from cypher_dsl.expressions.operators import boolean_operation

        return boolean_operation("AND", self, other)

    def __or__(self, other: Condition) -> Condition:
        """Build a disjunction. Python's ``or`` cannot be overloaded."""
        from cypher_dsl.expressions.operators import boolean_operation

        return boolean_operation("OR", self, other)

    def __invert__(self) -> Condition:
        """Build a negation. Python's ``not`` cannot be overloaded."""
        from cypher_dsl.expressions.operators import unary_condition

        return unary_condition("NOT", self)

    def __getitem__(self, key: str | int | Expression) -> Expression:
        """
        Access a property or a subscripted value.

        A string key is a static property name and is quoted as a name. An integer or
        an expression key is syntax inside brackets, so ``row[param("key")]`` renders
        a parameter instead of interpolating its text.

        Args:
            key: Property name, integer index, or expression key.

        Returns:
            A property or subscript node, which can be chained.

        Raises:
            DslError: If the base expression is an alias, which is a projection rather
                than a value.
        """
        from cypher_dsl.expressions.properties import Property, SubscriptExpression
        from cypher_dsl.expressions.values import SymbolicName, lit

        if isinstance(key, str):
            return Property(self, SymbolicName(key))
        if isinstance(key, Expression):
            return SubscriptExpression(self, key)
        return SubscriptExpression(self, lit(key))

    def alias(self, alias: str) -> AliasedExpression:
        """
        Project this expression under another name.

        The alias is kept as a name, not as text, so identifier quoting stays a
        rendering decision. The import is deferred because the expression modules
        depend on this module for the base class.

        Args:
            alias: Name the projection receives in the result.

        Returns:
            A projection item that renders this expression followed by ``AS`` and the
            quoted alias.

        Raises:
            InvalidIdentifierError: At render time, when the name is empty or contains
                a prohibited control character.
        """
        from cypher_dsl.expressions.values import AliasedExpression, SymbolicName

        return AliasedExpression(expression=self, alias_name=SymbolicName(alias))


# Alias values are built when the module is imported, so they sit below the classes they
# name. The recursive members stay strings, which `|` rejects when the alias is built.
LiteralInput: TypeAlias = Union[  # noqa: UP007
    bool,
    int,
    float,
    str,
    bytes,
    date,
    datetime,
    time,
    timedelta,
    Sequence["LiteralInput"],
    Mapping[str, "LiteralInput"],
    None,
]

ExpressionInput: TypeAlias = LiteralInput | Expression | NamedExpression

ProjectionInput: TypeAlias = ExpressionInput


def coerce_expression(value: ExpressionInput) -> Expression:
    """
    Turn a Python value or a named pattern into an expression node.

    A bare string stays a literal here. Only projection positions treat a string as a
    variable name, which keeps function arguments and comparison operands from
    silently referring to a name that happens to match the value.

    Args:
        value: Literal data, an expression or a node with an expression form.

    Returns:
        The original expression, the named node's variable reference, or a literal.

    Raises:
        DslError: If the value is an alias, which is a projection and not a value.
        InvalidLiteralError: If the value cannot become a literal.
    """
    from cypher_dsl.expressions.values import lit

    if isinstance(value, NamedExpression):
        return require_operand(value.as_expression())
    if isinstance(value, Expression):
        return require_operand(value)
    return lit(value)


def require_operand(expression: Expression) -> Expression:
    """
    Reject an alias where an expression operand is required.

    ``x AS y`` is a projection item. Passing it to an operator would render text such
    as ``x AS y + 1``, which is not an expression. The alias stays valid only in a
    projection position.

    Args:
        expression: Candidate operand.

    Returns:
        The same expression when it is a value.

    Raises:
        DslError: If the expression is an :class:`AliasedExpression`.
    """
    from cypher_dsl.expressions.values import AliasedExpression

    if isinstance(expression, AliasedExpression):
        raise DslError("An alias is a projection, not an operand. Alias the finished expression instead.")
    return expression

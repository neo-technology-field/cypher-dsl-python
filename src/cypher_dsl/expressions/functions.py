"""
Function invocations, built-in element identifiers, stars and trusted text.

Function names are syntax, not data: a qualified name is validated and quoted segment
by segment. The library does not inspect installed procedures or reject functions it
does not recognise, because an unknown name may still be a user-defined function.
"""

from __future__ import annotations

from dataclasses import dataclass

from cypher_dsl.errors import DslError, InvalidIdentifierError
from cypher_dsl.expressions.base import Expression, ExpressionInput, Precedence, coerce_expression, require_operand
from cypher_dsl.syntax import AstNode, _require_tuple


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class FunctionInvocation(Expression):
    """
    A call to a Cypher function.

    Attributes:
        function_name: Name segments in call order. ``point.distance`` is two segments.
        arguments: Argument expressions, in call order.
        distinct: Whether the call aggregates distinct values.
    """

    function_name: tuple[str, ...]
    arguments: tuple[Expression, ...]
    distinct: bool = False

    def __post_init__(self) -> None:
        """
        Reject an empty name segment, an alias argument or ``DISTINCT *``.

        Raises:
            InvalidIdentifierError: If a name segment is empty.
            DslError: If an argument is an alias, or ``DISTINCT`` is applied to a star.
        """
        _require_tuple(self.function_name, "Function name segments")
        _require_tuple(self.arguments, "Function arguments")
        if not self.function_name or any(not segment for segment in self.function_name):
            raise InvalidIdentifierError("A function name needs at least one non-empty segment.")
        for argument in self.arguments:
            require_operand(argument)
        if self.distinct and any(isinstance(argument, Asterisk) for argument in self.arguments):
            raise DslError("DISTINCT cannot be applied to an asterisk argument.")

    def children(self) -> tuple[AstNode, ...]:
        """Expose the arguments in call order."""
        return self.arguments


@dataclass(frozen=True, eq=False, init=False, weakref_slot=True, slots=True)
class ElementId(FunctionInvocation):
    """
    A logical element identifier that always renders as ``elementId(n)``.

    The operation is the same on every supported server: return the identifier of a node
    or relationship. Keeping it a logical node means callers do not write the function
    name and generic ``fn("id", ...)`` is never rewritten.
    """

    def __init__(self, operand: Expression) -> None:
        """Wrap the expression whose element identifier is requested."""
        object.__setattr__(self, "function_name", ("elementId",))
        object.__setattr__(self, "arguments", (require_operand(operand),))
        object.__setattr__(self, "distinct", False)
        self.__post_init__()


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class Asterisk(Expression):
    """
    The explicit ``*`` projection or argument.

    A star is a node rather than a convention about the string ``"*"``, so a literal
    string can never turn into a projection by accident.
    """


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class RawExpression(Expression):
    """
    Trusted Cypher expression text that the library does not escape or certify.

    Attributes:
        text: Expression source exactly as supplied by the caller.
    """

    text: str

    def __post_init__(self) -> None:
        """Reject empty text, which cannot form an expression."""
        if not self.text.strip():
            raise DslError("raw() needs non-empty Cypher expression text.")

    @property
    def precedence(self) -> Precedence:
        """
        Return the lowest level so a surrounding operator groups the text.

        The library cannot know which operators the trusted text contains. Treating it
        as the weakest binding makes a parent add parentheses rather than silently
        changing the grouping of the caller's expression.
        """
        return Precedence.OR


def fn(function_name: str, *arguments: ExpressionInput) -> FunctionInvocation:
    """
    Call a function by name.

    Args:
        function_name: Name or dot-qualified name, such as ``point.distance``.
        arguments: Argument expressions or literal values. A bare string is a literal.

    Returns:
        A function invocation node.

    Raises:
        InvalidIdentifierError: If a name segment is empty.
        DslError: If an argument is an alias.
    """
    segments = tuple(function_name.split("."))
    return FunctionInvocation(segments, tuple(coerce_expression(argument) for argument in arguments))


def count(value: ExpressionInput, distinct: bool = False) -> FunctionInvocation:
    """
    Build a ``count`` invocation.

    Args:
        value: Expression to count, or :func:`asterisk` for every row.
        distinct: Count distinct values instead of all occurrences.

    Returns:
        A ``count`` invocation.

    Raises:
        DslError: If ``distinct`` is combined with an asterisk.
    """
    return FunctionInvocation(("count",), (coerce_expression(value),), distinct)


def element_id(value: ExpressionInput) -> ElementId:
    """
    Return the element identifier of a node or relationship.

    This renders ``elementId(value)``. ``fn("id", ...)`` keeps the function name the caller supplied.
    """
    return ElementId(coerce_expression(value))


def asterisk() -> Asterisk:
    """Return the explicit ``*`` expression used by projections and ``count``."""
    return Asterisk()


def raw(text: str) -> RawExpression:
    """
    Wrap trusted Cypher expression text.

    The text is rendered unchanged. It is an escape hatch for syntax the library does
    not model, so no escaping or validation is applied.

    Args:
        text: Non-empty expression source.

    Returns:
        An opaque expression node.

    Raises:
        DslError: If the text is empty or whitespace only.
    """
    return RawExpression(text)


__all__ = [
    "Asterisk",
    "ElementId",
    "FunctionInvocation",
    "RawExpression",
    "asterisk",
    "count",
    "element_id",
    "fn",
    "raw",
]

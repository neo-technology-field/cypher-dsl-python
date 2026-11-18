"""
Label expressions: the predicates a node pattern's labels and a relationship's types are built
from.

The term classes cover the Cypher label-expression grammar: names, the ``%`` wildcard, colon
conjunctions as written by ``with_labels``, and the ``&``, ``|`` and ``!`` operators. A label
expression is pattern syntax, not a value expression, so no term can stand where ``RETURN`` or
a filter expects an expression.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING

from cypher_dsl.ast import AstNode, _require_tuple
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.values import SymbolicName, validate_name

if TYPE_CHECKING:
    from cypher_dsl.patterns.nodes import PatternElement


class LabelPrecedence(IntEnum):
    """Binding strength of one label term, from disjunction up to an atom."""

    DISJUNCTION = 1
    CONJUNCTION = 2
    NEGATION = 3
    ATOM = 4


def _require_label_term(value: object, construct: str) -> None:
    """Reject a direct-construction operand that is not a label expression."""
    if not isinstance(value, LabelExpression):
        raise DslError(f"{construct} holds label expression terms, not {type(value).__name__}.")


class LabelExpression(AstNode):
    """
    Base for every label-expression term, carrying the shared operators.

    Subclasses are frozen dataclasses that state their binding strength through
    ``precedence``. The operators build terms without coercing strings, because a bare
    string in a label position is ambiguous with the plain-label form the factories accept.
    """

    __slots__ = ()

    @property
    def precedence(self) -> LabelPrecedence:
        """Return the term's binding strength."""
        raise NotImplementedError

    def __and__(self, other: object) -> LabelExpression:
        """Combine two terms into a conjunction rendered with ``&``."""
        if not isinstance(other, LabelExpression):
            return NotImplemented
        return LabelConjunction(self, other)

    def __or__(self, other: object) -> LabelExpression:
        """Combine two terms into a disjunction rendered with ``|``."""
        if not isinstance(other, LabelExpression):
            return NotImplemented
        return LabelDisjunction(self, other)

    def __invert__(self) -> LabelExpression:
        """Negate this term so it renders with a leading ``!``."""
        return LabelNegation(self)


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class LabelName(LabelExpression):
    """
    One label or relationship type name.

    Attributes:
        name: The name as written in the pattern.
    """

    name: SymbolicName

    def __post_init__(self) -> None:
        """
        Reject a name that no identifier position can carry.

        Raises:
            InvalidIdentifierError: If the name fails name validation.
        """
        validate_name(self.name.value)

    @property
    def precedence(self) -> LabelPrecedence:
        """Return the atom level: a single name binds tightest."""
        return LabelPrecedence.ATOM


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class AnyLabel(LabelExpression):
    """The ``%`` wildcard: true when the matched element has at least one label."""

    @property
    def precedence(self) -> LabelPrecedence:
        """Return the atom level: the wildcard binds tightest."""
        return LabelPrecedence.ATOM


ANY_LABEL = AnyLabel()


def label(name: str) -> LabelName:
    """
    Build one label or relationship type term.

    Args:
        name: Label or relationship type name.

    Returns:
        A term that combines with ``&``, ``|`` and ``~``, and that ``node()`` and the
        relationship factories accept in label and type positions.

    Raises:
        InvalidIdentifierError: If the name fails name validation.
    """
    return LabelName(SymbolicName(name))


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class ColonConjunction(LabelExpression):
    """
    Plain labels joined by a colon, the form ``with_labels`` writes.

    Attributes:
        terms: Label names in insertion order, primary first.
    """

    terms: tuple[LabelName, ...]

    def __post_init__(self) -> None:
        """
        Reject fewer than two terms or a term that is not a label name.

        Raises:
            DslError: If the terms are not a tuple of at least two label names.
        """
        _require_tuple(self.terms, "Colon conjunction terms")
        if len(self.terms) < 2:
            raise DslError("A colon conjunction joins at least two label names.")
        for term in self.terms:
            if not isinstance(term, LabelName):
                raise DslError(f"A colon conjunction holds label names, not {type(term).__name__}.")

    def children(self) -> tuple[AstNode, ...]:
        """Expose the label names in rendered order."""
        return self.terms

    @property
    def precedence(self) -> LabelPrecedence:
        """Return the atom level: a colon list is one unit."""
        return LabelPrecedence.ATOM


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class LabelConjunction(LabelExpression):
    """
    Two terms joined by ``&``.

    Attributes:
        left: Term on the left.
        right: Term on the right.
    """

    left: LabelExpression
    right: LabelExpression

    def __post_init__(self) -> None:
        """
        Reject an operand that is not a label expression.

        Raises:
            DslError: If either operand is not a LabelExpression.
        """
        _require_label_term(self.left, "A conjunction")
        _require_label_term(self.right, "A conjunction")

    def children(self) -> tuple[AstNode, ...]:
        """Expose both operands in rendered order."""
        return (self.left, self.right)

    @property
    def precedence(self) -> LabelPrecedence:
        """Return the conjunction level, between negation and disjunction."""
        return LabelPrecedence.CONJUNCTION


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class LabelDisjunction(LabelExpression):
    """
    Two terms joined by ``|``.

    Attributes:
        left: Term on the left.
        right: Term on the right.
    """

    left: LabelExpression
    right: LabelExpression

    def __post_init__(self) -> None:
        """
        Reject an operand that is not a label expression.

        Raises:
            DslError: If either operand is not a LabelExpression.
        """
        _require_label_term(self.left, "A disjunction")
        _require_label_term(self.right, "A disjunction")

    def children(self) -> tuple[AstNode, ...]:
        """Expose both operands in rendered order."""
        return (self.left, self.right)

    @property
    def precedence(self) -> LabelPrecedence:
        """Return the disjunction level, the loosest binding."""
        return LabelPrecedence.DISJUNCTION


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class LabelNegation(LabelExpression):
    """
    A term negated with ``!``.

    Attributes:
        operand: Term the negation applies to.
    """

    operand: LabelExpression

    def __post_init__(self) -> None:
        """
        Reject an operand that is not a label expression.

        Raises:
            DslError: If the operand is not a LabelExpression.
        """
        _require_label_term(self.operand, "A negation")

    def children(self) -> tuple[AstNode, ...]:
        """Expose the negated term."""
        return (self.operand,)

    @property
    def precedence(self) -> LabelPrecedence:
        """Return the negation level, above conjunction and below an atom."""
        return LabelPrecedence.NEGATION


def require_plain_labels(pattern: PatternElement, construct: str, remedy: str) -> None:
    """
    Reject a label expression a write clause cannot render.

    CREATE and MERGE attach labels; a ``&``, ``|``, ``!`` or ``%`` term states a match
    predicate, not labels to attach.

    Args:
        pattern: Pattern element to check.
        construct: Clause keyword used in the failure message.
        remedy: Call-site advice that completes the failure message.

    Raises:
        DslError: If any node pattern's label expression is not a plain label list.
    """
    for node in pattern.nodes():
        if not isinstance(node.label_expression, (LabelName, ColonConjunction)):
            raise DslError(f"{construct} accepts plain labels on a node, not a label expression. {remedy}")


__all__ = [
    "ANY_LABEL",
    "AnyLabel",
    "ColonConjunction",
    "LabelConjunction",
    "LabelDisjunction",
    "LabelExpression",
    "LabelName",
    "LabelNegation",
    "LabelPrecedence",
    "label",
    "require_plain_labels",
]

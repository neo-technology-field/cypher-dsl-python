"""
Label expression predicates in expression positions.

A label predicate tests a node's labels or a relationship's type against a label
expression built from ``label()`` terms. The colon form renders ``element:labels``
and every supported release parses it; the ``IS [NOT] LABELED`` form requires
Neo4j 2026.04 and Cypher 25.
"""

from __future__ import annotations

from dataclasses import dataclass

from cypher_dsl.ast import AstNode
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.base import Expression, NamedExpression, Precedence, require_operand
from cypher_dsl.expressions.operators import Condition
from cypher_dsl.patterns.labels import ColonConjunction, LabelExpression, label


def _element_expression(element: object) -> Expression:
    """
    Turn the tested element into an expression operand.

    Args:
        element: A named node or relationship pattern, or an expression.

    Returns:
        The pattern's variable reference or the expression itself.

    Raises:
        DslError: If the element is an alias, or is neither a named pattern nor an
            expression. A bare string is rejected because it would be a literal value,
            not a node or relationship.
    """
    if isinstance(element, NamedExpression):
        return require_operand(element.as_expression())
    if isinstance(element, Expression):
        return require_operand(element)
    raise DslError(
        "A label predicate tests a node or a relationship, "
        f"not {type(element).__name__}. Pass a named pattern or an expression."
    )


def _labels_term(labels: object) -> LabelExpression:
    """
    Turn the labels argument into one label expression term.

    Args:
        labels: One label or type name, or a term built from ``label()``.

    Returns:
        The name as a label name term, or the term itself.

    Raises:
        DslError: If the value is neither a name nor a label expression.
        InvalidIdentifierError: If a name fails name validation.
    """
    if isinstance(labels, str):
        return label(labels)
    if isinstance(labels, LabelExpression):
        return labels
    raise DslError(f"Labels must be a name or a label expression, not {type(labels).__name__}.")


def _reject_colon_conjunction(expression: LabelExpression) -> None:
    """
    Reject a colon list in a predicate's label expression.

    The expression-position grammar combines terms with ``&``, ``|`` and ``!`` only;
    a colon list is the plain-label form of a node pattern.

    Args:
        expression: Label expression to inspect, including every nested term.

    Raises:
        DslError: If any term, including the root, is a colon conjunction.
    """
    if isinstance(expression, ColonConjunction):
        raise DslError("A label predicate has no colon list. Write label('A') & label('B') instead.")
    for child in expression.children():
        if isinstance(child, LabelExpression):
            _reject_colon_conjunction(child)


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class HasLabel(Condition):
    """
    The colon form of a label predicate.

    Attributes:
        operand: Expression whose labels or type are tested, usually a variable.
        labels: Label expression the element must match.
    """

    operand: Expression
    labels: LabelExpression

    def __post_init__(self) -> None:
        """
        Reject an alias operand, a labels value that is not a label expression, or a colon list.

        Raises:
            DslError: If the operand is an alias, the labels value is not a label expression,
                or any label term is a colon conjunction.
        """
        require_operand(self.operand)
        if not isinstance(self.labels, LabelExpression):
            raise DslError(f"A label predicate holds a label expression, not {type(self.labels).__name__}.")
        _reject_colon_conjunction(self.labels)

    @property
    def precedence(self) -> Precedence:
        """Return the comparison level, where the grammar places a label predicate."""
        return Precedence.COMPARISON

    def children(self) -> tuple[AstNode, ...]:
        """Expose the tested element and the label expression in rendered order."""
        return (self.operand, self.labels)


def has_label(element: NamedExpression | Expression, labels: str | LabelExpression) -> HasLabel:
    """
    Build the colon form of a label predicate.

    Args:
        element: Named node or relationship pattern, or an expression whose value the
            predicate tests.
        labels: One label or type name, or a label expression built from ``label()``
            terms with ``&``, ``|`` and ``~``.

    Returns:
        A predicate rendering ``element:labels``, such as ``p:Manager`` or
        ``p:Manager|Director``.

    Raises:
        DslError: If the element is not a named pattern or expression, the element is
            an alias, or the labels contain a colon list.
        InvalidIdentifierError: If a label name fails name validation.
    """
    return HasLabel(_element_expression(element), _labels_term(labels))


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class IsLabeled(Condition):
    """
    The ``IS [NOT] LABELED`` form of a label predicate.

    The negation applies to the whole label expression, which differs from a ``!``
    term inside it.

    Attributes:
        operand: Expression whose labels or type are tested, usually a variable.
        labels: Label expression the element must match.
        negated: Whether the predicate renders ``IS NOT LABELED``.
    """

    operand: Expression
    labels: LabelExpression
    negated: bool = False

    def __post_init__(self) -> None:
        """
        Reject an alias operand, a labels value that is not a label expression, or a colon list.

        Raises:
            DslError: If the operand is an alias, the labels value is not a label expression,
                or any label term is a colon conjunction.
        """
        require_operand(self.operand)
        if not isinstance(self.labels, LabelExpression):
            raise DslError(f"A label predicate holds a label expression, not {type(self.labels).__name__}.")
        _reject_colon_conjunction(self.labels)

    @property
    def precedence(self) -> Precedence:
        """Return the comparison level, where the grammar places a label predicate."""
        return Precedence.COMPARISON

    def children(self) -> tuple[AstNode, ...]:
        """Expose the tested element and the label expression in rendered order."""
        return (self.operand, self.labels)


def is_labeled(element: NamedExpression | Expression, labels: str | LabelExpression) -> IsLabeled:
    """
    Build the ``IS LABELED`` form of a label predicate.

    Args:
        element: Named node or relationship pattern, or an expression whose value the
            predicate tests.
        labels: One label or type name, or a label expression built from ``label()``
            terms with ``&``, ``|`` and ``~``.

    Returns:
        A predicate rendering ``element IS LABELED labels``. Requires Neo4j 2026.04
        and Cypher 25, so a render against an older release or a ``CYPHER 5`` pin is
        refused.

    Raises:
        DslError: If the element is not a named pattern or expression, the element is
            an alias, or the labels contain a colon list.
        InvalidIdentifierError: If a label name fails name validation.
    """
    return IsLabeled(_element_expression(element), _labels_term(labels))


def is_not_labeled(element: NamedExpression | Expression, labels: str | LabelExpression) -> IsLabeled:
    """
    Build the ``IS NOT LABELED`` form of a label predicate.

    The negation applies to the whole label expression, which differs from ``~`` on
    one term: ``is_not_labeled(n, label('A') & label('B'))`` is false for a node with
    both labels, while ``is_labeled(n, ~label('A') & label('B'))`` asks for ``B``
    without ``A``.

    Args:
        element: Named node or relationship pattern, or an expression whose value the
            predicate tests.
        labels: One label or type name, or a label expression built from ``label()``
            terms with ``&``, ``|`` and ``~``.

    Returns:
        A predicate rendering ``element IS NOT LABELED labels``. Requires Neo4j
        2026.04 and Cypher 25, so a render against an older release or a ``CYPHER 5``
        pin is refused.

    Raises:
        DslError: If the element is not a named pattern or expression, the element is
            an alias, or the labels contain a colon list.
        InvalidIdentifierError: If a label name fails name validation.
    """
    return IsLabeled(_element_expression(element), _labels_term(labels), True)


__all__ = ["HasLabel", "IsLabeled", "has_label", "is_labeled", "is_not_labeled"]

"""
Relationships and the chains they form.

A single relationship keeps both of its endpoint nodes, so a chain can prove that adjacent
relationships meet at the same node instead of silently producing a path that reads as two.
Chains are built by extending from the current endpoint, which is why a chain never needs to
copy or rename an endpoint.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from cypher_dsl.ast import AstNode, _require_tuple
from cypher_dsl.errors import DslError, EmptyPatternError
from cypher_dsl.expressions.base import Expression, ExpressionInput, NamedExpression
from cypher_dsl.expressions.values import SymbolicName, Variable, validate_name
from cypher_dsl.patterns.labels import ColonConjunction, LabelExpression, LabelName
from cypher_dsl.patterns.nodes import NodePattern, PatternElement, PatternProperties, coerce_pattern_properties


class RelationshipDirection(Enum):
    """Direction of a relationship, read from the pattern's left node."""

    OUTGOING = "outgoing"
    INCOMING = "incoming"
    UNDIRECTED = "undirected"


def _require_single_type(expression: LabelExpression) -> None:
    """
    Reject a type expression that joins labels with a colon anywhere in its tree.

    A relationship carries exactly one relationship type. A colon conjunction is the plain-label
    form that ``with_labels`` writes, which no position in a relationship's type expression can
    hold; a disjunction of names is the supported way to state the types a relationship may
    match.

    Args:
        expression: Type expression to inspect, including every nested term.

    Raises:
        DslError: If any term in the expression is a ColonConjunction.
    """
    if isinstance(expression, ColonConjunction):
        raise DslError("A relationship has exactly one type. Write a union as label('A') | label('B').")
    for child in expression.children():
        if isinstance(child, LabelExpression):
            _require_single_type(child)


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class Relationship(AstNode):
    """
    One relationship between two nodes.

    The left node is held for chain validation only and is deliberately not a rendered
    child: the element that owns the relationship renders every node exactly once. A
    relationship on its own is not a ``MATCH`` element, because a pattern always needs both ends.

    Attributes:
        left: Node the relationship starts from.
        right: Node the relationship reaches.
        direction: Arrow direction as written between the endpoints.
        type_expression: Relationship type predicate, or ``None`` for an untyped relationship.
        variable: Variable that binds the relationship, or ``None`` when anonymous.
        properties: Explicit property map, whole-map expression, or ``None``.
    """

    left: NodePattern
    right: NodePattern
    direction: RelationshipDirection
    type_expression: LabelExpression | None = None
    variable: SymbolicName | None = None
    properties: PatternProperties | Expression | None = None

    def __post_init__(self) -> None:
        """
        Reject an impossible relationship or a type expression a relationship cannot carry.

        Raises:
            DslError: If an endpoint is not a node pattern, the direction is not a
                direction value, the type expression is not a label expression, or the type
                expression contains a colon conjunction.
            InvalidIdentifierError: If a name fails validation.
        """
        if not isinstance(self.left, NodePattern) or not isinstance(self.right, NodePattern):
            raise DslError("A relationship connects two node patterns.")
        if not isinstance(self.direction, RelationshipDirection):
            raise DslError(f"{self.direction!r} is not a relationship direction.")
        if self.type_expression is not None:
            if not isinstance(self.type_expression, LabelExpression):
                raise DslError(
                    f"A relationship type must be a label expression, not {type(self.type_expression).__name__}."
                )
            _require_single_type(self.type_expression)
        if self.variable is not None:
            validate_name(self.variable.value)

    def children(self) -> tuple[AstNode, ...]:
        """Expose the type expression, property map and reached node in rendered order."""
        children: list[AstNode] = []
        if self.type_expression is not None:
            children.append(self.type_expression)
        if self.properties is not None:
            children.append(self.properties)
        children.append(self.right)
        return tuple(children)


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class RelationshipPattern(PatternElement, NamedExpression):
    """
    A chain of one or more relationships.

    The chain is the grammar element: ``MATCH`` accepts a chain, not a bare relationship. Every
    relationship after the first must start at the node the previous relationship reached, so a
    chain cannot describe two different nodes with one name.

    Attributes:
        relationships: Relationships in traversal order.
    """

    relationships: tuple[Relationship, ...]

    def __post_init__(self) -> None:
        """
        Reject an empty chain, a non-relationship element or a broken endpoint sequence.

        Raises:
            EmptyPatternError: If the chain has no relationships.
            DslError: If an element is not a relationship, or adjacent relationships do not meet
                at the same node pattern object.
        """
        _require_tuple(self.relationships, "Relationship pattern list")
        if not self.relationships:
            raise EmptyPatternError("A relationship pattern needs at least one relationship.")
        for relationship in self.relationships:
            if not isinstance(relationship, Relationship):
                raise DslError(
                    f"A relationship pattern holds Relationship elements, not {type(relationship).__name__}."
                )
        for previous, following in zip(self.relationships, self.relationships[1:], strict=False):
            if previous.right is not following.left:
                raise DslError(
                    "Adjacent relationships in a chain must share the same endpoint node pattern. "
                    "Extend the chain through relationship_to, relationship_from or relationship_with instead."
                )

    @property
    def start(self) -> NodePattern:
        """Return the node the chain starts from."""
        return self.relationships[0].left

    @property
    def endpoint(self) -> NodePattern:
        """Return the node the chain currently reaches."""
        return self.relationships[-1].right

    @property
    def direction(self) -> RelationshipDirection:
        """Return the direction of the last relationship."""
        return self.relationships[-1].direction

    def children(self) -> tuple[AstNode, ...]:
        """Expose the start node and the relationships in rendered order."""
        return (self.start, *self.relationships)

    def nodes(self) -> tuple[NodePattern, ...]:
        """Return every node in the chain, start first and then each reached node."""
        return (self.start, *(relationship.right for relationship in self.relationships))

    def property_maps(self) -> tuple[PatternProperties | Expression, ...]:
        """Return every node and relationship property map in the chain."""
        maps: list[PatternProperties | Expression] = [
            properties for properties in (node.properties for node in self.nodes()) if properties is not None
        ]
        maps.extend(
            relationship.properties for relationship in self.relationships if relationship.properties is not None
        )
        return tuple(maps)

    def as_expression(self) -> Expression:
        """
        Return the variable that represents the chain's last relationship.

        Returns:
            A variable reference, never the relationship type or its properties.

        Raises:
            DslError: If the last relationship is anonymous.
        """
        variable = self.relationships[-1].variable
        if variable is None:
            raise DslError(
                "An anonymous relationship pattern has no variable. "
                "Give the relationship a name before using it as an expression."
            )
        return Variable(variable)

    def __getitem__(self, key: str | int | Expression) -> Expression:
        """
        Read a property of the chain's last relationship.

        Args:
            key: Property name, integer index or expression key.

        Returns:
            A property or subscript expression on the relationship variable.

        Raises:
            DslError: If the last relationship is anonymous.
        """
        return self.as_expression()[key]

    def relationship_to(
        self,
        target: NodePattern,
        relationship_type: str | LabelExpression | None = None,
        name: str | None = None,
        properties: Mapping[str, ExpressionInput] | Expression | None = None,
    ) -> RelationshipPattern:
        """
        Extend the chain with an outgoing relationship from its current endpoint.

        Returns:
            A new chain whose last relationship reaches ``target``.

        Raises:
            DslError: If ``target`` is not a node pattern.
            InvalidIdentifierError: If a name fails validation.
        """
        return self._extend(target, RelationshipDirection.OUTGOING, relationship_type, name, properties)

    def relationship_from(
        self,
        target: NodePattern,
        relationship_type: str | LabelExpression | None = None,
        name: str | None = None,
        properties: Mapping[str, ExpressionInput] | Expression | None = None,
    ) -> RelationshipPattern:
        """
        Extend the chain with an incoming relationship from ``target``.

        Returns:
            A new chain whose last relationship is reached from ``target``.

        Raises:
            DslError: If ``target`` is not a node pattern.
            InvalidIdentifierError: If a name fails validation.
        """
        return self._extend(target, RelationshipDirection.INCOMING, relationship_type, name, properties)

    def relationship_with(
        self,
        target: NodePattern,
        relationship_type: str | LabelExpression | None = None,
        name: str | None = None,
        properties: Mapping[str, ExpressionInput] | Expression | None = None,
    ) -> RelationshipPattern:
        """
        Extend the chain with an undirected relationship to ``target``.

        Returns:
            A new chain whose last relationship is undirected.

        Raises:
            DslError: If ``target`` is not a node pattern.
            InvalidIdentifierError: If a name fails validation.
        """
        return self._extend(target, RelationshipDirection.UNDIRECTED, relationship_type, name, properties)

    def _extend(
        self,
        target: NodePattern,
        direction: RelationshipDirection,
        relationship_type: str | LabelExpression | None,
        name: str | None,
        properties: Mapping[str, ExpressionInput] | Expression | None,
    ) -> RelationshipPattern:
        relationship = _relationship(self.endpoint, target, direction, relationship_type, name, properties)
        return RelationshipPattern((*self.relationships, relationship))


def relationship_pattern(
    source: NodePattern,
    target: NodePattern,
    direction: RelationshipDirection,
    relationship_type: str | LabelExpression | None = None,
    name: str | None = None,
    properties: Mapping[str, ExpressionInput] | Expression | None = None,
) -> RelationshipPattern:
    """
    Build a single-relationship pattern between two node patterns.

    The helper exists so that the three direction factories share one validation path
    instead of each repeating the endpoint and name checks.

    Args:
        source: Node the relationship starts from, as written.
        target: Node at the far end of the relationship.
        direction: Arrow direction between the endpoints.
        relationship_type: Relationship type or type expression to match, or ``None`` for an untyped relationship.
        name: Optional variable that binds the relationship.
        properties: Explicit property entries, whole-map expression, or ``None``.

    Returns:
        A single-relationship pattern that can be extended further.

    Raises:
        DslError: If an endpoint is not a node pattern.
        InvalidIdentifierError: If a name fails validation.
    """
    if not isinstance(source, NodePattern):
        raise DslError(f"A relationship endpoint must be a node pattern, not {type(source).__name__}.")
    if not isinstance(target, NodePattern):
        raise DslError(f"A relationship endpoint must be a node pattern, not {type(target).__name__}.")
    relationship = _relationship(source, target, direction, relationship_type, name, properties)
    return RelationshipPattern((relationship,))


def _coerce_type_expression(relationship_type: str | LabelExpression | None) -> LabelExpression | None:
    """Turn a factory argument into a type term, refusing anything a relationship cannot hold."""
    if relationship_type is None or isinstance(relationship_type, LabelExpression):
        return relationship_type
    if not isinstance(relationship_type, str):
        raise DslError(
            f"A relationship type must be a string or a label expression, not {type(relationship_type).__name__}."
        )
    return LabelName(SymbolicName(relationship_type))


def _relationship(
    source: NodePattern,
    target: NodePattern,
    direction: RelationshipDirection,
    relationship_type: str | LabelExpression | None,
    name: str | None,
    properties: Mapping[str, ExpressionInput] | Expression | None,
) -> Relationship:
    return Relationship(
        left=source,
        right=target,
        direction=direction,
        type_expression=_coerce_type_expression(relationship_type),
        variable=None if name is None else SymbolicName(name),
        properties=coerce_pattern_properties(properties),
    )


__all__ = [
    "Relationship",
    "RelationshipDirection",
    "RelationshipPattern",
    "relationship_pattern",
]

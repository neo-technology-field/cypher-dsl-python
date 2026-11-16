"""
Node patterns and their explicit property maps.

A pattern is syntax, not a rendered entity. The variable name is a reference that other
expressions can use; labels and property maps describe what to match. The three are
separate so a label cannot appear in ``RETURN`` and a pattern can be reused in several
clauses without carrying renderer state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cypher_dsl.errors import DslError, EmptyPatternError
from cypher_dsl.expressions.base import Expression, ExpressionInput, NamedExpression, coerce_expression, require_operand
from cypher_dsl.expressions.values import SymbolicName, Variable, validate_name
from cypher_dsl.syntax import AstNode, _require_tuple, structurally_equal

if TYPE_CHECKING:
    from cypher_dsl.patterns.relationships import RelationshipPattern


class PatternElement(AstNode):
    """
    Base for an element that can stand in a ``MATCH`` pattern list.

    Subclasses declare the nodes and property maps they contain so that clause
    validation can inspect a pattern without knowing its concrete class.
    """

    __slots__ = ()

    def nodes(self) -> tuple[NodePattern, ...]:
        """Return every node pattern the element contains, in syntax order."""
        return ()

    def property_maps(self) -> tuple[PatternProperties | Expression, ...]:
        """Return every property map the element carries, in syntax order."""
        return ()


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class PatternProperties(AstNode):
    """
    An explicit property map inside a pattern, snapshotted at construction.

    Entries keep their source order and their values as expressions. A caller may change
    the mapping afterwards without changing the pattern, which is why the map is copied
    instead of stored. A whole-map expression is deliberately not represented here: it
    is a different grammar form and the owning clause decides whether it is allowed.

    Attributes:
        entries: Property name and value pairs in insertion order.
    """

    entries: tuple[tuple[SymbolicName, Expression], ...]

    def __post_init__(self) -> None:
        """
        Reject a property name that no identifier position can carry, or an alias value.

        Direct construction is a public path, so it applies the same operand check the
        mapping factory reaches through coercion. An alias is a projection item, not a
        value, and rendering it inside a pattern map would produce invalid syntax.

        Raises:
            InvalidIdentifierError: If a property name fails name validation.
            DslError: If a value is an aliased projection.
        """
        _require_tuple(self.entries, "Pattern property entries")
        for entry in self.entries:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise DslError("A pattern property entry must be a tuple containing a key and value pair.")
            key, value = entry
            validate_name(key.value)
            require_operand(value)

    def children(self) -> tuple[AstNode, ...]:
        """Expose the property values in their rendered order."""
        return tuple(value for _, value in self.entries)

    @classmethod
    def from_mapping(cls, items: Mapping[str, ExpressionInput]) -> PatternProperties:
        """
        Snapshot a caller's mapping into typed entries.

        Args:
            items: Property names and values. Bare strings stay literal values.

        Returns:
            A pattern map that no longer observes later changes to ``items``.
        """
        return cls(tuple((SymbolicName(key), coerce_expression(value)) for key, value in items.items()))


def coerce_pattern_properties(
    properties: Mapping[str, ExpressionInput] | Expression | None,
) -> PatternProperties | Expression | None:
    """
    Turn a caller's property argument into a pattern map or a whole-map expression.

    An expression is kept as it is so that the owning clause can accept or reject the
    whole-map form. A mapping becomes an explicit map, because that is the only form a
    read pattern can render here.

    Args:
        properties: Explicit property entries, a whole-map expression, or nothing.

    Returns:
        A pattern map, the unchanged expression, or ``None``.

    Raises:
        DslError: If the value is neither a mapping, an expression nor ``None``.
    """
    if properties is None or isinstance(properties, Expression):
        return properties
    if not isinstance(properties, Mapping):
        raise DslError(f"Pattern properties must be a mapping or an expression, not {type(properties).__name__}.")
    return PatternProperties.from_mapping(properties)


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class NodePattern(PatternElement, NamedExpression):
    """
    A node pattern with at least one label and an optional variable.

    The variable is the pattern's identity. It is not a ``name`` property: property maps
    use a separate argument, so ``node("Person", name="p")`` produces no property at all.

    Attributes:
        labels: Labels in insertion order, primary first.
        variable: Variable the pattern binds, or ``None`` when it is anonymous.
        properties: Explicit property map, whole-map expression, or ``None``.
    """

    labels: tuple[SymbolicName, ...]
    variable: SymbolicName | None = None
    properties: PatternProperties | Expression | None = None

    def __post_init__(self) -> None:
        """
        Reject an unlabelled node or a name that cannot be an identifier.

        Raises:
            EmptyPatternError: If no label is present.
            InvalidIdentifierError: If a label or the variable fails name validation.
        """
        _require_tuple(self.labels, "Node labels")
        if not self.labels:
            raise EmptyPatternError("A node pattern needs at least one label.")
        for label in self.labels:
            validate_name(label.value)
        if self.variable is not None:
            validate_name(self.variable.value)

    def children(self) -> tuple[AstNode, ...]:
        """Expose the property map when the pattern has one."""
        return () if self.properties is None else (self.properties,)

    def nodes(self) -> tuple[NodePattern, ...]:
        """Return this node as the only node pattern."""
        return (self,)

    def property_maps(self) -> tuple[PatternProperties | Expression, ...]:
        """Return the property map when the pattern has one."""
        return () if self.properties is None else (self.properties,)

    def as_expression(self) -> Variable:
        """
        Return the variable that represents this pattern in an expression position.

        Returns:
            A variable reference, never the pattern's labels or properties.

        Raises:
            DslError: If the pattern is anonymous. Inventing a name would bind a
                variable the caller never asked for.
        """
        if self.variable is None:
            raise DslError(
                "An anonymous node pattern has no variable. Give the pattern a name before using it as an expression."
            )
        return Variable(self.variable)

    def __getitem__(self, key: str | int | Expression) -> Expression:
        """
        Read a property of the pattern's variable.

        Args:
            key: Property name, integer index or expression key.

        Returns:
            A property or subscript expression on the variable reference.

        Raises:
            DslError: If the pattern is anonymous.
        """
        return self.as_expression()[key]

    def with_labels(self, *labels: str) -> NodePattern:
        """
        Return a copy with additional labels.

        The original pattern is not changed, so two statements can share a prefix pattern
        and extend it differently.

        Args:
            labels: Additional labels. Duplicates and labels already present are ignored.

        Returns:
            A new node pattern with unique labels in insertion order.

        Raises:
            DslError: If no label is supplied.
            InvalidIdentifierError: If a label fails name validation.
        """
        if not labels:
            raise DslError("with_labels requires at least one label.")
        merged = list(self.labels)
        for label in labels:
            symbolic = SymbolicName(label)
            validate_name(symbolic.value)
            if symbolic not in merged:
                merged.append(symbolic)
        return NodePattern(tuple(merged), self.variable, self.properties)

    def relationship_to(
        self,
        target: NodePattern,
        relationship_type: str,
        name: str | None = None,
        properties: Mapping[str, ExpressionInput] | Expression | None = None,
    ) -> RelationshipPattern:
        """
        Start an outgoing relationship from this node to ``target``.

        Args:
            target: Node pattern at the far end of the relationship.
            relationship_type: Relationship type to match.
            name: Optional variable that binds the relationship.
            properties: Explicit property entries, whole-map expression, or ``None``.

        Returns:
            A one-hop relationship pattern, which can be extended further.

        Raises:
            DslError: If ``target`` is not a node pattern.
            InvalidIdentifierError: If a name fails validation.
        """
        from cypher_dsl.patterns.relationships import RelationshipDirection, relationship_pattern

        return relationship_pattern(self, target, RelationshipDirection.OUTGOING, relationship_type, name, properties)

    def relationship_from(
        self,
        target: NodePattern,
        relationship_type: str,
        name: str | None = None,
        properties: Mapping[str, ExpressionInput] | Expression | None = None,
    ) -> RelationshipPattern:
        """
        Start an incoming relationship from ``target`` into this node.

        Args:
            target: Node pattern at the source of the incoming relationship.
            relationship_type: Relationship type to match.
            name: Optional variable that binds the relationship.
            properties: Explicit property entries, whole-map expression, or ``None``.

        Returns:
            A one-hop relationship pattern, which can be extended further.

        Raises:
            DslError: If ``target`` is not a node pattern.
            InvalidIdentifierError: If a name fails validation.
        """
        from cypher_dsl.patterns.relationships import RelationshipDirection, relationship_pattern

        return relationship_pattern(self, target, RelationshipDirection.INCOMING, relationship_type, name, properties)

    def relationship_with(
        self,
        target: NodePattern,
        relationship_type: str,
        name: str | None = None,
        properties: Mapping[str, ExpressionInput] | Expression | None = None,
    ) -> RelationshipPattern:
        """
        Start an undirected relationship between this node and ``target``.

        Args:
            target: Node pattern at the other end of the relationship.
            relationship_type: Relationship type to match.
            name: Optional variable that binds the relationship.
            properties: Explicit property entries, whole-map expression, or ``None``.

        Returns:
            A one-hop relationship pattern, which can be extended further.

        Raises:
            DslError: If ``target`` is not a node pattern.
            InvalidIdentifierError: If a name fails validation.
        """
        from cypher_dsl.patterns.relationships import RelationshipDirection, relationship_pattern

        return relationship_pattern(self, target, RelationshipDirection.UNDIRECTED, relationship_type, name, properties)


def _same_node_declaration(left: NodePattern, right: NodePattern) -> bool:
    """Compare declaration content without treating an alias as a different node."""
    if left.labels != right.labels:
        return False
    if left.properties is None or right.properties is None:
        return left.properties is None and right.properties is None
    return structurally_equal(left.properties, right.properties)


def node(
    primary_label: str,
    name: str | None = None,
    properties: Mapping[str, ExpressionInput] | Expression | None = None,
) -> NodePattern:
    """
    Build a node pattern with one primary label.

    Args:
        primary_label: First label. At least one label is required by the grammar.
        name: Optional variable that binds the node in the surrounding clause.
        properties: Explicit property entries, whole-map expression, or ``None``.

    Returns:
        An immutable node pattern. Use ``with_labels`` for further labels.

    Raises:
        InvalidIdentifierError: If the label or variable fails name validation.
        DslError: If ``properties`` is not a mapping, an expression or ``None``.
    """
    return NodePattern(
        labels=(SymbolicName(primary_label),),
        variable=None if name is None else SymbolicName(name),
        properties=coerce_pattern_properties(properties),
    )


__all__ = [
    "NodePattern",
    "PatternElement",
    "PatternProperties",
    "coerce_pattern_properties",
    "node",
]

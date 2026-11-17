"""
Write clauses and the typed update nodes they own.

An update is not a comparison. ``SET n.x = 1`` and ``n.x == 1`` share a spelling in Cypher
but mean different things, so the assignment is its own node rather than an overload of
expression equality. Map replacement and map patching are also different operations, and
the node keeps which one was requested instead of leaving the renderer to guess from the
right-hand expression.

A ``MERGE`` owns its actions. They are not free-standing clauses, so an action stays
with the pattern whose identity it depends on. Each action owns one update
tuple, which is why a second ``ON CREATE`` on the same merge is rejected rather than
rendered as two actions with the same meaning.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, TypeAlias

from cypher_dsl.clauses.base import Clause
from cypher_dsl.errors import DslError, EmptyPatternError
from cypher_dsl.expressions.base import Expression, ExpressionInput, NamedExpression, coerce_expression, require_operand
from cypher_dsl.expressions.collections import MapExpression
from cypher_dsl.expressions.properties import Property, SubscriptExpression
from cypher_dsl.expressions.values import Literal, Parameter, SymbolicName, Variable, _FrozenMap, validate_name
from cypher_dsl.patterns.nodes import PatternElement, PatternProperties, require_explicit_properties
from cypher_dsl.patterns.relationships import RelationshipDirection, RelationshipPattern
from cypher_dsl.ast import AstNode, _require_tuple

if TYPE_CHECKING:
    from cypher_dsl.statements.builder import StatementBuilder

_REFERENCE_TARGETS = (Variable, Property, SubscriptExpression)


class UpdateKind(Enum):
    """Which property update an assignment performs."""

    ASSIGN = "="
    PATCH = "+="


def _require_update_target(target: Expression, kind: UpdateKind) -> None:
    """
    Reject an assignment target that cannot occupy its grammar position.

    ``SET n = value`` accepts a variable or a property reference. The ``+=`` form is a
    property patch on a node or relationship, so its left side must be the binding
    variable itself. A property on the left of ``+=`` would read as a nested-map update,
    which Cypher does not have.
    """
    if kind is UpdateKind.PATCH:
        if isinstance(target, Variable):
            return
        raise DslError(
            f"A SET += patch target must be a binding variable, not {type(target).__name__}. "
            "Patch the element's properties with the element variable."
        )
    if isinstance(target, _REFERENCE_TARGETS):
        return
    raise DslError(f"A SET assignment target must be a variable or property reference, not {type(target).__name__}.")


def _require_create_properties(pattern: PatternElement) -> None:
    """
    Reject a CREATE property form that the grammar does not allow.

    ``CREATE`` accepts an explicit property map, a map expression, a map-valued literal
    or a general parameter reference. A scalar literal or a variable that holds a map is
    a value expression in a position the grammar does not accept, so callers use an
    explicit map or ``SET`` instead. This is structural checking, not runtime map type
    inference.
    """
    for properties in pattern.property_maps():
        if isinstance(properties, (PatternProperties, Parameter, MapExpression)):
            continue
        if isinstance(properties, Literal) and isinstance(properties.value, _FrozenMap):
            continue
        raise DslError(
            "CREATE pattern properties accept an explicit map, a map expression, a map literal "
            f"or a whole-map parameter, not {type(properties).__name__}. "
            "A variable that holds a map needs a SET operation."
        )


def _require_create_relationships(pattern: PatternElement) -> None:
    """
    Reject relationship hops that CREATE cannot write.

    MERGE permits an undirected relationship, but CREATE needs an explicit direction.
    Both write clauses require exactly one type. Untyped relationships remain valid
    in read patterns only.
    """
    if not isinstance(pattern, RelationshipPattern):
        return
    for hop in pattern.relationships:
        if hop.direction is RelationshipDirection.UNDIRECTED:
            raise DslError(
                "CREATE relationships need a direction. Use relationship_to or relationship_from "
                "instead of relationship_with."
            )
    _require_relationship_types(pattern, "CREATE")


def _require_relationship_types(pattern: PatternElement, keyword: str) -> None:
    """Reject untyped write hops without imposing CREATE's direction rule on MERGE."""
    if isinstance(pattern, RelationshipPattern):
        for hop in pattern.relationships:
            if hop.relationship_type is None:
                raise DslError(f"{keyword} relationships need exactly one relationship type.")


def _require_label_target(target: Expression) -> Variable:
    """Return the variable a label update applies to."""
    if isinstance(target, Variable):
        return target
    raise DslError(
        f"A label update target must be a named pattern or variable, not {type(target).__name__}. "
        "Use the node pattern or name() for the element whose labels change."
    )


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class Assignment(AstNode):
    """
    A property assignment or property patch.

    Attributes:
        target: Variable or property reference being written.
        value: Expression whose runtime value is assigned or merged into the target.
        kind: ``SET`` replacement or ``+=`` patch of the properties named by ``value``.
    """

    target: Expression
    value: Expression
    kind: UpdateKind = UpdateKind.ASSIGN

    def __post_init__(self) -> None:
        """
        Reject an invalid target, an alias value or an unknown update kind.

        Raises:
            DslError: If the target is not a reference, the value is an alias, or the
                update kind is not one of the two property updates.
        """
        if not isinstance(self.kind, UpdateKind):
            raise DslError(f"An assignment kind is SET or +=, not {type(self.kind).__name__}.")
        require_operand(self.target)
        _require_update_target(self.target, self.kind)
        require_operand(self.value)

    def children(self) -> tuple[AstNode, ...]:
        """Expose the target and value in rendered order."""
        return (self.target, self.value)


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class LabelUpdate(AstNode):
    """
    One or more labels added to or removed from a named element.

    Attributes:
        target: Variable whose labels change.
        labels: Label names in the order they should render. At least one is required.
    """

    target: Variable
    labels: tuple[SymbolicName, ...]

    def __post_init__(self) -> None:
        """
        Reject an empty label list, a non-variable target or an invalid label name.

        Raises:
            DslError: If the target is not a variable or no label is supplied.
            InvalidIdentifierError: If a label fails name validation.
        """
        _require_tuple(self.labels, "Label update labels")
        if not isinstance(self.target, Variable):
            raise DslError(f"A label update target must be a variable, not {type(self.target).__name__}.")
        if not self.labels:
            raise DslError("A label update requires at least one label.")
        for label in self.labels:
            if not isinstance(label, SymbolicName):
                raise DslError(f"A label update holds label names, not {type(label).__name__}.")
            validate_name(label.value)

    def children(self) -> tuple[AstNode, ...]:
        """Expose the target as the only child."""
        return (self.target,)


def assign(target: ExpressionInput, value: ExpressionInput) -> Assignment:
    """
    Replace properties with the given value.

    ``SET n = $map`` removes every property the map does not mention. Use
    :func:`update_properties` to patch only the named properties.

    Args:
        target: Variable or property reference to write.
        value: Expression or literal data whose value replaces the target.

    Returns:
        An assignment node rendered with ``=``.

    Raises:
        DslError: If the target cannot name something to update.
    """
    return Assignment(coerce_expression(target), coerce_expression(value), UpdateKind.ASSIGN)


def update_properties(target: ExpressionInput, value: ExpressionInput) -> Assignment:
    """
    Patch the properties named by a map, leaving the others in place.

    Args:
        target: Variable or property reference to write.
        value: Map, parameter pointing to a map, or expression whose value is merged.

    Returns:
        An assignment node rendered with ``+=``.

    Raises:
        DslError: If the target cannot name something to update.
    """
    return Assignment(coerce_expression(target), coerce_expression(value), UpdateKind.PATCH)


def set_labels(target: NamedExpression | Variable, *labels: str) -> LabelUpdate:
    """
    Add labels to a named node as one update.

    The labels are a typed node rather than raw strings so ``SET`` and ``REMOVE`` render
    the same shape and neither form can be confused with a property value.

    Args:
        target: Named node pattern or variable whose labels change.
        labels: One or more label names.

    Returns:
        A label update usable in ``SET`` or ``REMOVE``.

    Raises:
        DslError: If the target is anonymous or not a variable, or no label is supplied.
        InvalidIdentifierError: If a label name is invalid.
    """
    if not labels:
        raise DslError("A label update requires at least one label.")
    if isinstance(target, RelationshipPattern):
        raise DslError("Labels apply to nodes, not relationships. Update a relationship property instead.")
    variable = _require_label_target(target.as_expression() if isinstance(target, NamedExpression) else target)
    ordered: dict[str, None] = {}
    for label in labels:
        validate_name(label)
        ordered.setdefault(label, None)
    return LabelUpdate(variable, tuple(SymbolicName(label) for label in ordered))


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class CreateClause(Clause):
    """
    A ``CREATE`` clause holding one or more patterns.

    Unlike ``MATCH`` and ``MERGE``, ``CREATE`` accepts a whole-map expression for a
    pattern's properties: the server can read that map when it creates the element. An
    explicit map, a map expression, a map-valued literal and a parameter are all valid
    forms, while a scalar literal or a variable in this position is rejected.

    Attributes:
        patterns: Patterns in rendered order. At least one is required.
    """

    patterns: tuple[PatternElement, ...]

    def __post_init__(self) -> None:
        """
        Reject an empty body, a non-pattern item or an unwritable pattern shape.

        Raises:
            EmptyPatternError: If no pattern is present.
            DslError: If a pattern is not a pattern element, its properties are neither
                an explicit map nor a parameter, a relationship is undirected, or a
                relationship has no type. The collection must also be a tuple.
        """
        _require_tuple(self.patterns, "CREATE patterns")
        if not self.patterns:
            raise EmptyPatternError("CREATE requires at least one pattern.")
        for pattern in self.patterns:
            if not isinstance(pattern, PatternElement):
                raise DslError(f"CREATE accepts pattern elements, not {type(pattern).__name__}.")
            _require_create_properties(pattern)
            _require_create_relationships(pattern)

    def children(self) -> tuple[AstNode, ...]:
        """Expose the patterns in rendered order."""
        return self.patterns


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class MergeAction(AstNode):
    """
    One ``ON CREATE`` or ``ON MATCH`` action owned by a merge.

    Attributes:
        keyword: Action keyword, ``ON CREATE`` or ``ON MATCH``.
        updates: Assignments applied by the action. At least one is required.
    """

    keyword: str
    updates: tuple[Assignment, ...]

    def __post_init__(self) -> None:
        """
        Reject an unknown keyword, an empty update list or a non-assignment.

        Raises:
            DslError: If the keyword is not one of the two merge actions, the update
                collection is not a non-empty tuple, or an update is not an assignment.
        """
        if self.keyword not in {"ON CREATE", "ON MATCH"}:
            raise DslError(f"MERGE actions are ON CREATE or ON MATCH, not {self.keyword!r}.")
        _require_tuple(self.updates, f"{self.keyword} updates")
        if not self.updates:
            raise DslError(f"{self.keyword} requires at least one assignment.")
        for update in self.updates:
            if not isinstance(update, Assignment):
                raise DslError(f"{self.keyword} accepts assignments, not {type(update).__name__}.")

    def children(self) -> tuple[AstNode, ...]:
        """Expose the assignments in rendered order."""
        return self.updates


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class MergeClause(Clause):
    """
    A ``MERGE`` clause with its single identity pattern and attached actions.

    Attributes:
        pattern: Pattern the server searches for before creating it.
        actions: ``ON CREATE`` and ``ON MATCH`` actions in call order. At most one action
            of each kind is allowed.
    """

    pattern: PatternElement
    actions: tuple[MergeAction, ...] = ()

    def __post_init__(self) -> None:
        """
        Reject an invalid pattern, a whole-map identity or duplicate actions.

        Raises:
            DslError: If the pattern is not a pattern element, uses a whole-map property
                expression, or the action list is not a tuple of distinct merge actions.
        """
        if not isinstance(self.pattern, PatternElement):
            raise DslError(f"MERGE accepts one pattern element, not {type(self.pattern).__name__}.")
        require_explicit_properties(
            self.pattern, "MERGE", "Write the identity properties explicitly in the pattern, or use map_()."
        )
        _require_relationship_types(self.pattern, "MERGE")
        _require_tuple(self.actions, "MERGE actions")
        seen: set[str] = set()
        for action in self.actions:
            if not isinstance(action, MergeAction):
                raise DslError(f"MERGE holds merge actions, not {type(action).__name__}.")
            if action.keyword in seen:
                raise DslError(
                    f"MERGE already has an {action.keyword} action. Put multiple assignments in the one action call."
                )
            seen.add(action.keyword)

    def children(self) -> tuple[AstNode, ...]:
        """Expose the pattern, followed by the actions in call order."""
        return (self.pattern, *self.actions)

    @property
    def on_create(self) -> tuple[Assignment, ...]:
        """Return the ``ON CREATE`` assignments, or an empty tuple."""
        return next((action.updates for action in self.actions if action.keyword == "ON CREATE"), ())

    @property
    def on_match(self) -> tuple[Assignment, ...]:
        """Return the ``ON MATCH`` assignments, or an empty tuple."""
        return next((action.updates for action in self.actions if action.keyword == "ON MATCH"), ())

    def with_action(self, action: MergeAction) -> MergeClause:
        """
        Return a copy with one more action appended.

        Args:
            action: ``ON CREATE`` or ``ON MATCH`` action to attach.

        Returns:
            A new merge clause; the original is unchanged.

        Raises:
            DslError: If an action of the same kind is already attached.
        """
        return MergeClause(self.pattern, (*self.actions, action))


Update: TypeAlias = Assignment | LabelUpdate


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class SetClause(Clause):
    """
    A ``SET`` clause holding property and label updates.

    Attributes:
        updates: Updates in rendered order. At least one is required.
    """

    updates: tuple[Assignment | LabelUpdate, ...]

    def __post_init__(self) -> None:
        """
        Reject an empty update list or an unsupported update node.

        Raises:
            DslError: If the collection is not a non-empty tuple of updates.
        """
        _require_tuple(self.updates, "SET updates")
        if not self.updates:
            raise DslError("SET requires at least one update.")
        for update in self.updates:
            if not isinstance(update, (Assignment, LabelUpdate)):
                raise DslError(f"SET accepts assignments and label updates, not {type(update).__name__}.")

    def children(self) -> tuple[AstNode, ...]:
        """Expose the updates in rendered order."""
        return self.updates


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class RemoveClause(Clause):
    """
    A ``REMOVE`` clause holding property references and label updates.

    Attributes:
        targets: Property references or label updates in rendered order. At least one is
            required.
    """

    targets: tuple[Expression | LabelUpdate, ...]

    def __post_init__(self) -> None:
        """
        Reject a literal, arithmetic expression or empty target list.

        Raises:
            DslError: If the collection is not a non-empty tuple, or a target is neither a
                property reference nor a label update.
        """
        _require_tuple(self.targets, "REMOVE targets")
        if not self.targets:
            raise DslError("REMOVE requires at least one target.")
        for target in self.targets:
            if isinstance(target, (Property, SubscriptExpression, LabelUpdate)):
                continue
            raise DslError(
                f"REMOVE accepts a property reference or a label update, not {type(target).__name__}. "
                "Use a property reference or set_labels()."
            )

    def children(self) -> tuple[AstNode, ...]:
        """Expose the targets in rendered order."""
        return self.targets


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class DeleteClause(Clause):
    """
    A ``DELETE`` or ``DETACH DELETE`` clause holding named element references.

    Attributes:
        targets: Variables naming nodes or relationships to delete.
        detach: Whether relationships attached to the targets are deleted as well.
    """

    targets: tuple[Variable, ...]
    detach: bool = False

    def __post_init__(self) -> None:
        """
        Reject an empty target list or an expression that names no element.

        Raises:
            DslError: If the collection is not a non-empty tuple of variables, or
                ``detach`` is not a boolean.
        """
        _require_tuple(self.targets, "DELETE targets")
        if not self.targets:
            raise DslError("DELETE requires at least one target.")
        for target in self.targets:
            if not isinstance(target, Variable):
                raise DslError(
                    f"DELETE accepts named element references, not {type(target).__name__}. "
                    "Pass the named pattern or name() of the element to delete."
                )
        if not isinstance(self.detach, bool):
            raise DslError(f"DETACH DELETE is a boolean choice, not {type(self.detach).__name__}.")

    def children(self) -> tuple[AstNode, ...]:
        """Expose the targets in rendered order."""
        return self.targets


def create(*patterns: PatternElement) -> StatementBuilder:
    """
    Start a statement with a ``CREATE`` clause.

    Args:
        patterns: One or more patterns in rendered order.

    Returns:
        A new builder whose only clause is ``CREATE``. It is finalisable without a
        ``RETURN`` because creation is a complete write.

    Raises:
        EmptyPatternError: If no pattern is supplied.
        DslError: If a pattern is not a pattern element.
    """
    from cypher_dsl.statements.builder import StatementBuilder

    return StatementBuilder().create(*patterns)


def merge(pattern: PatternElement) -> StatementBuilder:
    """
    Start a statement with a ``MERGE`` clause.

    Args:
        pattern: The single identity pattern. Its properties are written explicitly; a
            whole-map expression is rejected because the server cannot use it as
            identity without inspecting the map first.

    Returns:
        A new builder whose only clause is ``MERGE``. It is finalisable without a
        ``RETURN``.

    Raises:
        DslError: If the pattern is not a pattern element or uses a whole-map property
            expression.
    """
    from cypher_dsl.statements.builder import StatementBuilder

    return StatementBuilder().merge(pattern)


__all__ = [
    "Assignment",
    "CreateClause",
    "DeleteClause",
    "LabelUpdate",
    "MergeAction",
    "MergeClause",
    "RemoveClause",
    "SetClause",
    "Update",
    "UpdateKind",
    "assign",
    "create",
    "merge",
    "set_labels",
    "update_properties",
]

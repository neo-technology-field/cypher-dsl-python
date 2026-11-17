"""
Shared contracts for abstract syntax tree nodes: child order, bound names and structural comparison.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from typing import TypeAlias

from cypher_dsl.errors import DslError

OccurrencePath: TypeAlias = tuple[int, ...]


class OccurrenceFacts:
    """Base for read-only semantic facts attached to one AST occurrence."""

    __slots__ = ()


def _require_tuple(value: object, field: str) -> None:
    """Reject mutable syntax containers before a frozen node can retain them."""
    if not isinstance(value, tuple):
        raise DslError(f"{field} must be a tuple, not {type(value).__name__}.")


class _Visitor:
    """Receive node-entry and node-exit callbacks with no-op defaults."""

    __slots__ = ()

    def enter(self, node: AstNode) -> None:
        """Ignore a node entry."""

    def leave(self, node: AstNode) -> None:
        """Ignore a node exit."""


class AstNode:
    """
    Base for every syntax node.

    Subclasses declare their children in documented syntax order by overriding
    ``children``. They must not override ``accept``: keeping traversal in one place is
    what makes every visitor see the same order.

    Nodes are expected to be frozen dataclasses. The base class carries no state, so a
    leaf node needs neither an instance dictionary nor a custom initialiser.
    """

    __slots__ = ()

    def children(self) -> tuple[AstNode, ...]:
        """Return the child nodes in documented syntax order."""
        return ()

    def local_names(self) -> tuple[str, ...]:
        """
        Return the names this node binds for its own subtree, empty for ordinary nodes.

        Clause and statement bindings live in scope frames. This hook covers bindings
        an expression introduces inside itself, such as a comprehension variable, so
        reference checking does not mistake them for references to an outer name.
        """
        return ()

    def accept(self, visitor: _Visitor) -> None:
        """Walk this node and its descendants, calling enter and leave in order."""
        visitor.enter(self)
        for child in self.children():
            child.accept(visitor)
        visitor.leave(self)


def structurally_equal(left: AstNode, right: AstNode) -> bool:
    """
    Compare two syntax trees by node type and named field values.

    Expression equality is reserved for building predicates, so it cannot also answer
    "are these trees the same". This function walks node types, dataclass fields,
    tuples, lists and mappings explicitly. Value objects such as ``SymbolicName`` and
    frozen literal records compare through their own equality, which is defined on
    values rather than on node identity.

    Args:
        left: First tree to compare.
        right: Second tree to compare.

    Returns:
        True when both trees have the same shape and equal field values.
    """
    return _structurally_equal(left, right)


def _structurally_equal(left: object, right: object) -> bool:
    if left is right:
        return True
    if type(left) is not type(right):
        return False
    if isinstance(left, AstNode):
        if not is_dataclass(left):
            return True
        return all(_structurally_equal(getattr(left, field.name), getattr(right, field.name)) for field in fields(left))
    if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
        return len(left) == len(right) and all(
            _structurally_equal(left_item, right_item) for left_item, right_item in zip(left, right, strict=True)
        )
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return len(left) == len(right) and all(
            key in right and _structurally_equal(value, right[key]) for key, value in left.items()
        )
    return left == right

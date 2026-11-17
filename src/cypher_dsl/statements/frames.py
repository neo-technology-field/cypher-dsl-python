"""
Scope frames and the shared semantic vocabulary.

A frame is the value one position in a statement sees: the visible names, whether a
projection boundary closed them, whether the context around the position is complete,
which names later clauses may not rebind, the node identities pattern rules recorded,
and the names whose identities an enclosing context may still supply. Rules in ``statements/rules`` derive the next
frame from the construct in front of it, so a prefix can grow into several branches without changing another branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from cypher_dsl.features import Capability
from cypher_dsl.patterns.nodes import NodePattern
from cypher_dsl.ast import AstNode, OccurrenceFacts, OccurrencePath

if TYPE_CHECKING:
    from cypher_dsl.expressions.values import Variable


@dataclass(frozen=True, weakref_slot=True, slots=True)
class ScopeFrame:
    """
    Referenceable names and deferred node identities at one position in a statement.

    Attributes:
        names: Visible names in binding order, or ``None`` when a trusted raw
            projection made them uncertifiable.
        closed: Whether a projection boundary or a called body's seed restricts
            references to ``names``. An open frame leaves references to unbound
            names tolerated rather than rejected.
        certified: Whether the context around this position is complete. The render root certifies. A called body's seed
            inherits its enclosing certification and certifies when the call explicitly imports nothing. A ``WITH``
            boundary closes the frame without certifying it. Import existence is checked in closed or certified frames.
        reserved: Names no later clause in this frame may rebind, however
            projections discard them. Imports populate it.
        bindings: Node identity by name, recorded by pattern rules and read by write
            rules. It distinguishes compatible write endpoints from conflicting
            redeclarations. It is not a schema or an inferred value type.
        unresolved: Names whose node identity an enclosing context may still supply, recorded by the call rule's seed
            and consumed by the write rules.
    """

    names: tuple[str, ...] | None = ()
    closed: bool = False
    certified: bool = False
    reserved: frozenset[str] = frozenset()
    bindings: tuple[tuple[str, NodePattern], ...] = ()
    unresolved: frozenset[str] = frozenset()


class DeclarationRole(Enum):
    """Whether a node pattern occurrence declares a name or refers to one."""

    DECLARE = "DECLARE"
    REFERENCE = "REFERENCE"


@dataclass(frozen=True, weakref_slot=True, slots=True)
class WriteDeclaration:
    """Classification of one node pattern occurrence in a write clause."""

    node: NodePattern
    role: DeclarationRole


@dataclass(frozen=True, weakref_slot=True, slots=True)
class NoFacts(OccurrenceFacts):
    """Facts for an occurrence that needs no additional semantic information."""


@dataclass(frozen=True, weakref_slot=True, slots=True)
class NodePatternFacts(OccurrenceFacts):
    """Declaration role for one node pattern occurrence."""

    role: DeclarationRole


@dataclass(frozen=True, weakref_slot=True, slots=True)
class SyntaxRequirement:
    """A capability required by one AST occurrence."""

    capability: Capability
    path: OccurrencePath


def merge_names(*groups: tuple[str, ...]) -> tuple[str, ...]:
    """Join name groups in first-declaration order without duplicates."""
    ordered: dict[str, None] = {}
    for group in groups:
        for name in group:
            ordered.setdefault(name, None)
    return tuple(ordered)


def reference_names(frame: ScopeFrame) -> tuple[str, ...] | None:
    """Return the names a reference may use, or ``None`` when checking is not safe."""
    return frame.names if frame.closed else None


def is_unresolved_node(frame: ScopeFrame, name: str) -> bool:
    """Return whether a name can have a node declaration supplied by a later enclosing call."""
    if name in frame.unresolved:
        return True
    if frame.certified or name in dict(frame.bindings):
        return False
    return frame.names is None or (not frame.closed and name not in frame.names)


def variables_in(node: AstNode) -> tuple[Variable, ...]:
    """Return the variables an expression tree contains, in traversal order."""
    from cypher_dsl.expressions.values import Variable

    found: list[Variable] = []
    if isinstance(node, Variable):
        found.append(node)
    for child in node.children():
        found.extend(variables_in(child))
    return tuple(found)


def free_variables_in(node: AstNode) -> tuple[Variable, ...]:
    """
    Return the variables a tree reads from its enclosing scope, in traversal order.

    A name a node binds through ``local_names`` is not a free reference inside that
    node's subtree, so a comprehension-style construct keeps its own variable out of
    the enclosing scope check.
    """
    found: list[Variable] = []
    _collect_free_variables(node, frozenset(), found)
    return tuple(found)


def _collect_free_variables(node: AstNode, bound: frozenset[str], found: list[Variable]) -> None:
    from cypher_dsl.expressions.values import Variable

    bound = bound | frozenset(node.local_names())
    if isinstance(node, Variable) and node.symbol.value not in bound:
        found.append(node)
    for child in node.children():
        _collect_free_variables(child, bound, found)


__all__ = [
    "DeclarationRole",
    "NoFacts",
    "NodePatternFacts",
    "ScopeFrame",
    "SyntaxRequirement",
    "WriteDeclaration",
    "free_variables_in",
    "is_unresolved_node",
    "merge_names",
    "reference_names",
    "variables_in",
]

"""Name bindings and expression references extracted from pattern lists."""

from __future__ import annotations

from cypher_dsl.expressions.values import Variable
from cypher_dsl.patterns.nodes import PatternElement, PatternProperties
from cypher_dsl.patterns.relationships import RelationshipPattern
from cypher_dsl.statements.frames import ScopeFrame, free_variables_in, merge_names


def pattern_transition(frame: ScopeFrame, patterns: tuple[PatternElement, ...]) -> ScopeFrame:
    """
    Return the frame after a pattern list binds its names.

    Names are added in pattern order. A name that already has a node identity keeps the
    first declaration, and a name that gains one is no longer deferred.
    """
    names = None if frame.names is None else merge_names(frame.names, pattern_bindings(patterns))
    bindings = dict(frame.bindings)
    for pattern in patterns:
        for node_pattern in pattern.nodes():
            if node_pattern.variable is not None:
                bindings.setdefault(node_pattern.variable.value, node_pattern)
    unresolved = frozenset(name for name in frame.unresolved if name not in bindings)
    return ScopeFrame(names, frame.closed, frame.certified, frame.reserved, tuple(bindings.items()), unresolved)


def pattern_bindings(patterns: tuple[PatternElement, ...]) -> tuple[str, ...]:
    """Return the names a pattern list binds, in pattern order."""
    names: list[str] = []
    for pattern in patterns:
        for node in pattern.nodes():
            if node.variable is not None:
                names.append(node.variable.value)
        if isinstance(pattern, RelationshipPattern):
            for relationship in pattern.relationships:
                if relationship.variable is not None:
                    names.append(relationship.variable.value)
    return merge_names(tuple(names))


def pattern_property_references(patterns: tuple[PatternElement, ...]) -> tuple[Variable, ...]:
    """
    Return the variables used by pattern property values.

    Those values are expressions, not declarations. A later ``MATCH`` pattern binds its
    own variables, but each property value still has to read a name that is available at
    that point in the statement.
    """
    references: list[Variable] = []
    for pattern in patterns:
        for properties in pattern.property_maps():
            if isinstance(properties, PatternProperties):
                for value in properties.children():
                    references.extend(free_variables_in(value))
            else:
                references.extend(free_variables_in(properties))
    return tuple(references)

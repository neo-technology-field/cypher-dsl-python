"""Construct renderers for node and relationship patterns."""

from __future__ import annotations

from typing import Final

from cypher_dsl.errors import DslError
from cypher_dsl.patterns.nodes import NodePattern, PatternProperties
from cypher_dsl.patterns.relationships import Relationship, RelationshipDirection, RelationshipPattern
from cypher_dsl.render.context import RenderContext
from cypher_dsl.render.expressions import _map_entries
from cypher_dsl.render.fragments import Fragment
from cypher_dsl.render.literals import quote_identifier
from cypher_dsl.render.rules import RuleBinding, bind
from cypher_dsl.statements.analysis import NodePatternFacts
from cypher_dsl.statements.scope import DeclarationRole

_DIRECTION_MARKS: Final = {
    RelationshipDirection.OUTGOING: ("-", "->"),
    RelationshipDirection.INCOMING: ("<-", "-"),
    RelationshipDirection.UNDIRECTED: ("-", "-"),
}


def node_pattern(node: NodePattern, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a node declaration, or only its variable when its occurrence is a reference."""
    if not isinstance(context.facts, NodePatternFacts):
        raise DslError("NodePattern rendering requires NodePatternFacts for its occurrence.")
    escape = context.always_escape_names
    if context.facts.role is DeclarationRole.REFERENCE:
        variable = "" if node.variable is None else quote_identifier(node.variable.value, escape)
        return f"({variable})"
    variable = "" if node.variable is None else quote_identifier(node.variable.value, escape)
    labels = ":".join(quote_identifier(label.value, escape) for label in node.labels)
    text = f"({variable}:{labels}"
    if children:
        text = f"{text} {children[0].text}"
    return f"{text})"


def pattern_properties(node: PatternProperties, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a pattern property map in entry order."""
    return _map_entries(node.entries, children, context.always_escape_names)


def relationship_pattern(node: RelationshipPattern, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render the start node and relationship hops without separators."""
    return "".join(child.text for child in children)


def relationship(node: Relationship, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render one directed or undirected relationship hop and its reached node."""
    escape = context.always_escape_names
    left_mark, right_mark = _DIRECTION_MARKS[node.direction]
    details = "" if node.variable is None else quote_identifier(node.variable.value, escape)
    if node.relationship_type is not None:
        details = f"{details}:{quote_identifier(node.relationship_type.value, escape)}"
    if node.properties is not None:
        properties_text = children[0].text
        details = properties_text if not details else f"{details} {properties_text}"
    target = children[-1].text
    bracket = "" if not details else f"[{details}]"
    return f"{left_mark}{bracket}{right_mark}{target}"


def pattern_bindings() -> tuple[RuleBinding, ...]:
    """Return the node and relationship pattern construct renderers."""
    return (
        bind(NodePattern, node_pattern),
        bind(PatternProperties, pattern_properties),
        bind(RelationshipPattern, relationship_pattern),
        bind(Relationship, relationship),
    )


__all__ = ["pattern_bindings"]

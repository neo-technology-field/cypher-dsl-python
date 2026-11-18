"""Construct renderers for node and relationship patterns and their label expressions."""

from __future__ import annotations

from typing import Final, cast

from cypher_dsl.errors import DslError
from cypher_dsl.patterns.labels import (
    AnyLabel,
    ColonConjunction,
    LabelConjunction,
    LabelDisjunction,
    LabelExpression,
    LabelName,
    LabelNegation,
    LabelPrecedence,
)
from cypher_dsl.patterns.nodes import NodePattern, PatternProperties
from cypher_dsl.patterns.relationships import Relationship, RelationshipDirection, RelationshipPattern
from cypher_dsl.render.context import RenderContext
from cypher_dsl.render.expressions import _map_entries
from cypher_dsl.render.fragments import Fragment
from cypher_dsl.render.literals import quote_identifier
from cypher_dsl.render.rules import RuleBinding, bind
from cypher_dsl.statements.frames import DeclarationRole, NodePatternFacts

_DIRECTION_MARKS: Final = {
    RelationshipDirection.OUTGOING: ("-", "->"),
    RelationshipDirection.INCOMING: ("<-", "-"),
    RelationshipDirection.UNDIRECTED: ("-", "-"),
}


def _grouped_term(fragment: Fragment, parent: LabelPrecedence, close_equal: bool) -> str:
    """Add parentheses when a label term binds less tightly than its parent."""
    child = cast(LabelExpression, fragment.node).precedence
    if child < parent or (close_equal and child == parent):
        return f"({fragment.text})"
    return fragment.text


def label_name(node: LabelName, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render one label or type name."""
    return quote_identifier(node.name.value, context.always_escape_names)


def any_label(node: AnyLabel, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render the wildcard that matches any labelled element."""
    return "%"


def colon_conjunction(node: ColonConjunction, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render plain labels joined by a colon."""
    return ":".join(child.text for child in children)


def label_conjunction(node: LabelConjunction, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render two terms joined by & with minimal parentheses."""
    left = _grouped_term(children[0], node.precedence, close_equal=False)
    right = _grouped_term(children[1], node.precedence, close_equal=True)
    return f"{left}&{right}"


def label_disjunction(node: LabelDisjunction, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render two terms joined by | with minimal parentheses."""
    left = _grouped_term(children[0], node.precedence, close_equal=False)
    right = _grouped_term(children[1], node.precedence, close_equal=True)
    return f"{left}|{right}"


def label_negation(node: LabelNegation, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a negated term; a same-level operand such as !!A needs no parentheses."""
    operand = _grouped_term(children[0], node.precedence, close_equal=False)
    return f"!{operand}"


def node_pattern(node: NodePattern, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a node declaration, or only its variable when its occurrence is a reference."""
    if not isinstance(context.facts, NodePatternFacts):
        raise DslError("NodePattern rendering requires NodePatternFacts for its occurrence.")
    escape = context.always_escape_names
    if context.facts.role is DeclarationRole.REFERENCE:
        variable = "" if node.variable is None else quote_identifier(node.variable.value, escape)
        return f"({variable})"
    variable = "" if node.variable is None else quote_identifier(node.variable.value, escape)
    text = f"({variable}:{children[0].text}"
    if len(children) > 1:
        text = context.layout.tokens(text, children[1].text)
    return f"{text})"


def pattern_properties(node: PatternProperties, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a pattern property map in entry order."""
    return _map_entries(node.entries, children, context)


def relationship_pattern(node: RelationshipPattern, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render the start node and relationships without separators."""
    return "".join(child.text for child in children)


def relationship(node: Relationship, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render one directed or undirected relationship and its reached node."""
    escape = context.always_escape_names
    left_mark, right_mark = _DIRECTION_MARKS[node.direction]
    details = "" if node.variable is None else quote_identifier(node.variable.value, escape)
    index = 0
    if node.type_expression is not None:
        details = f"{details}:{children[index].text}"
        index += 1
    if node.properties is not None:
        properties_text = children[index].text
        details = properties_text if not details else context.layout.tokens(details, properties_text)
    target = children[-1].text
    bracket = "" if not details else f"[{details}]"
    return f"{left_mark}{bracket}{right_mark}{target}"


def pattern_bindings() -> tuple[RuleBinding, ...]:
    """Return the node and relationship pattern construct renderers."""
    return (
        bind(LabelName, label_name),
        bind(AnyLabel, any_label),
        bind(ColonConjunction, colon_conjunction),
        bind(LabelConjunction, label_conjunction),
        bind(LabelDisjunction, label_disjunction),
        bind(LabelNegation, label_negation),
        bind(NodePattern, node_pattern),
        bind(PatternProperties, pattern_properties),
        bind(RelationshipPattern, relationship_pattern),
        bind(Relationship, relationship),
    )


__all__ = ["pattern_bindings"]

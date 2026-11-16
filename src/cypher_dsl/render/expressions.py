"""Construct renderers for expression and ordering nodes."""

from __future__ import annotations

from collections.abc import Sequence

from cypher_dsl.expressions.base import Expression, Precedence
from cypher_dsl.expressions.collections import ListExpression, MapExpression
from cypher_dsl.expressions.functions import Asterisk, ElementId, FunctionInvocation, RawExpression
from cypher_dsl.expressions.operators import BinaryOperation, Comparison, UnaryOperation, _ConditionOperand
from cypher_dsl.expressions.properties import Property, SubscriptExpression
from cypher_dsl.expressions.values import (
    AliasedExpression,
    Literal,
    Parameter,
    SortItem,
    SymbolicName,
    Variable,
)
from cypher_dsl.render.context import RenderContext
from cypher_dsl.render.fragments import Fragment
from cypher_dsl.render.literals import quote_function_segment, quote_identifier, quote_parameter_name, render_literal
from cypher_dsl.render.rules import RuleBinding, bind


def grouped(fragment: Fragment, parent: Precedence, close_equal: bool) -> str:
    """Add parentheses when a child binds less tightly than its parent."""
    node = fragment.node
    if not isinstance(node, Expression):
        return fragment.text
    child = node.precedence
    if child < parent or (close_equal and child == parent):
        return f"({fragment.text})"
    return fragment.text


def literal(node: Literal, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a literal value using the configured identifier escaping for nested map keys."""
    return render_literal(node.value, context.always_escape_names)


def variable(node: Variable, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a variable name."""
    return quote_identifier(node.symbol.value, context.always_escape_names)


def parameter(node: Parameter, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a parameter placeholder without collecting its binding."""
    name = node.symbol.value
    return f"${quote_parameter_name(name, context.always_escape_names)}"


def aliased_expression(node: AliasedExpression, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render an expression followed by its projection alias."""
    alias = quote_identifier(node.alias_name.value, context.always_escape_names)
    return f"{children[0].text} AS {alias}"


def comparison(node: Comparison, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a comparison or a postfix null test with structural operand grouping."""
    left = grouped(children[0], node.precedence, close_equal=True)
    if node.right is None:
        return f"{left} {node.operator}"
    right = grouped(children[1], node.precedence, close_equal=True)
    return f"{left} {node.operator} {right}"


def binary_operation(node: BinaryOperation, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render two operands and their arithmetic or logical operator."""
    left = grouped(children[0], node.precedence, close_equal=False)
    right = grouped(children[1], node.precedence, close_equal=True)
    return f"{left} {node.operator} {right}"


def unary_operation(node: UnaryOperation, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render unary arithmetic adjacent to its operand and NOT with a separating space."""
    operand = grouped(children[0], node.precedence, close_equal=node.operator in {"-", "+"})
    separator = "" if node.operator in {"-", "+"} else " "
    return f"{node.operator}{separator}{operand}"


def condition_operand(node: _ConditionOperand, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render an explicitly boolean operand without wrapper syntax."""
    return children[0].text


def property(node: Property, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render static property access on a structurally grouped base expression."""
    base = grouped(children[0], Precedence.ATOM, close_equal=False)
    key = quote_identifier(node.key.value, context.always_escape_names)
    return f"{base}.{key}"


def subscript_expression(node: SubscriptExpression, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a dynamic subscript on a structurally grouped base expression."""
    base = grouped(children[0], Precedence.ATOM, close_equal=False)
    return f"{base}[{children[1].text}]"


def list_expression(node: ListExpression, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render an ordered list expression."""
    return "[" + ", ".join(child.text for child in children) + "]"


def _map_entries(
    entries: Sequence[tuple[SymbolicName, Expression]],
    children: tuple[Fragment, ...],
    always_escape_names: bool,
) -> str:
    """Render entries as a map whose keys are identifiers and whose values are child fragments."""
    pairs = (
        f"{quote_identifier(key.value, always_escape_names)}: {child.text}"
        for child, (key, _) in zip(children, entries, strict=True)
    )
    return "{" + ", ".join(pairs) + "}"


def map_expression(node: MapExpression, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a map expression in entry order."""
    return _map_entries(node.entries, children, context.always_escape_names)


def element_id_function(node: ElementId, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render an element identifier as a call to ``elementId``."""
    return f"elementId({children[0].text})"


def function_invocation(node: FunctionInvocation, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a function name segment by segment, its arguments and an optional DISTINCT."""
    name = ".".join(quote_function_segment(segment) for segment in node.function_name)
    arguments = ", ".join(child.text for child in children)
    distinct = "DISTINCT " if node.distinct else ""
    return f"{name}({distinct}{arguments})"


def asterisk(node: Asterisk, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render an explicit asterisk."""
    return "*"


def raw_expression(node: RawExpression, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render trusted Cypher expression text unchanged."""
    return node.text


def sort_item(node: SortItem, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a sort key and its explicit direction."""
    return f"{children[0].text} {node.direction.value}"


def expression_bindings() -> tuple[RuleBinding, ...]:
    """Return the expression and ordering construct renderers."""
    return (
        bind(Literal, literal),
        bind(Variable, variable),
        bind(Parameter, parameter),
        bind(AliasedExpression, aliased_expression),
        bind(Comparison, comparison),
        bind(BinaryOperation, binary_operation),
        bind(UnaryOperation, unary_operation),
        bind(_ConditionOperand, condition_operand),
        bind(Property, property),
        bind(SubscriptExpression, subscript_expression),
        bind(ListExpression, list_expression),
        bind(MapExpression, map_expression),
        bind(ElementId, element_id_function),
        bind(FunctionInvocation, function_invocation),
        bind(Asterisk, asterisk),
        bind(RawExpression, raw_expression),
        bind(SortItem, sort_item),
    )


__all__ = ["element_id_function", "expression_bindings"]

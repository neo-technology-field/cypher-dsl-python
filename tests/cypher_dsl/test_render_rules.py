from dataclasses import dataclass

import pytest

from cypher_dsl.expressions.base import Expression, Precedence
from cypher_dsl.render.context import RenderContext
from cypher_dsl.render.expressions import grouped
from cypher_dsl.render.fragments import Fragment
from cypher_dsl.render.rules import RenderingRules, bind
from cypher_dsl.syntax import OccurrenceFacts


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class SyntheticExpression(Expression):
    value: str


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class SyntheticChild(SyntheticExpression):
    pass


class NoFacts(OccurrenceFacts):
    __slots__ = ()


def compose_parent(node: SyntheticExpression, children: tuple[Fragment, ...], context: RenderContext) -> str:
    return f"parent:{node.value}"


def compose_child(node: SyntheticChild, children: tuple[Fragment, ...], context: RenderContext) -> str:
    return f"child:{node.value}"


def test_rule_lookup_prefers_exact_type_then_mro() -> None:
    rules = RenderingRules.from_bindings((bind(SyntheticExpression, compose_parent),))
    assert rules.resolve(SyntheticChild("x")) is not None
    exact_rules = RenderingRules.from_bindings(
        (bind(SyntheticExpression, compose_parent), bind(SyntheticChild, compose_child))
    )
    assert (
        exact_rules.resolve(SyntheticChild("x")).compose(SyntheticChild("x"), (), RenderContext(False, NoFacts()))
        == "child:x"
    )
    assert (
        rules.resolve(SyntheticChild("x")).compose(SyntheticChild("x"), (), RenderContext(False, NoFacts()))
        == "parent:x"
    )


def test_duplicate_bindings_are_rejected() -> None:
    binding = bind(SyntheticExpression, compose_parent)
    with pytest.raises(ValueError, match="Duplicate rendering rule"):
        RenderingRules.from_bindings((binding, binding))


def test_grouped_uses_declared_precedence_not_text() -> None:
    fragment = Fragment(SyntheticExpression("x"), "x")
    assert grouped(fragment, Precedence.ATOM, close_equal=False) == "x"

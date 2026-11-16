"""Typed binding of AST classes to construct renderers."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TypeVar, cast

from cypher_dsl.errors import UnsupportedFeatureError
from cypher_dsl.render.context import RenderContext
from cypher_dsl.render.fragments import Fragment
from cypher_dsl.syntax import AstNode

TNode = TypeVar("TNode", bound=AstNode)
Compose = Callable[[TNode, tuple[Fragment, ...], RenderContext], str]
ErasedCompose = Callable[[AstNode, tuple[Fragment, ...], RenderContext], str]


class RenderingRule:
    """Nominal adapter contract between untyped traversal and a typed renderer."""

    __slots__ = ()

    def compose(self, node: AstNode, children: tuple[Fragment, ...], context: RenderContext) -> str:
        """Render one node from its completed child fragments."""
        raise NotImplementedError


@dataclass(frozen=True, weakref_slot=True, slots=True)
class RuleBinding:
    """One association between an AST class and its composition function."""

    node_type: type[AstNode]
    compose: ErasedCompose


class _BoundRule(RenderingRule):
    __slots__ = ("_binding",)

    def __init__(self, binding: RuleBinding) -> None:
        self._binding = binding

    def compose(self, node: AstNode, children: tuple[Fragment, ...], context: RenderContext) -> str:
        binding = self._binding
        if not isinstance(node, binding.node_type):
            raise UnsupportedFeatureError(
                f"Rendering rule for {binding.node_type.__name__} received {type(node).__name__}."
            )
        return binding.compose(node, children, context)


def bind(node_type: type[TNode], compose: Compose[TNode]) -> RuleBinding:
    """Bind one AST class to a renderer whose first argument has that type."""
    erased = cast(ErasedCompose, compose)
    return RuleBinding(node_type, erased)


class RenderingRules:
    """Immutable mapping from AST classes to the renderers selected for them."""

    __slots__ = ("_rules",)

    def __init__(self, rules: Mapping[type[AstNode], RenderingRule]) -> None:
        self._rules: Mapping[type[AstNode], RenderingRule] = MappingProxyType(dict(rules))

    @classmethod
    def from_bindings(cls, bindings: Iterable[RuleBinding]) -> RenderingRules:
        rules: dict[type[AstNode], RenderingRule] = {}
        for binding in bindings:
            if binding.node_type in rules:
                raise ValueError(f"Duplicate rendering rule for {binding.node_type.__name__}.")
            rules[binding.node_type] = _BoundRule(binding)
        return cls(rules)

    def resolve(self, node: AstNode) -> RenderingRule:
        """Return the exact rule or the nearest registered class in the node's MRO."""
        for node_type in type(node).__mro__:
            rule = self._rules.get(node_type)
            if rule is not None:
                return rule
        raise UnsupportedFeatureError(f"Rendering is not implemented for {type(node).__name__}.")


__all__ = ["RenderingRule", "RenderingRules", "RuleBinding", "bind"]

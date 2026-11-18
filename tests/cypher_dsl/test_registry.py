"""The class registry resolves a node to its nearest registered class."""

from __future__ import annotations

import pytest

from cypher_dsl.ast import AstNode
from cypher_dsl.registry import TypeRegistry


class _Base(AstNode):
    __slots__ = ()


class _Child(_Base):
    __slots__ = ()


class _Unregistered(AstNode):
    __slots__ = ()


def test_find_resolves_the_exact_class_first() -> None:
    registry = TypeRegistry({_Base: "base", _Child: "child"})
    assert registry.find(_Child()) == "child"


def test_find_resolves_the_nearest_registered_ancestor() -> None:
    registry = TypeRegistry({_Base: "base"})
    assert registry.find(_Child()) == "base"
    assert registry.find(_Base()) == "base"


def test_find_returns_none_for_an_unregistered_family() -> None:
    registry = TypeRegistry({_Base: "base"})
    assert registry.find(_Unregistered()) is None


def test_entries_cannot_be_mutated_through_the_registry() -> None:
    registry = TypeRegistry({_Base: "base"})
    with pytest.raises(TypeError):
        registry._entries[_Child] = "child"  # type: ignore[index]

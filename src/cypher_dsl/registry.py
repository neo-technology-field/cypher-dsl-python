"""The lookup table shared by the rendering and semantic rule registries."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Generic, TypeVar

from cypher_dsl.ast import AstNode

T = TypeVar("T")


class TypeRegistry(Generic[T]):
    """
    Lookup from AST classes to the value registered for each of them.

    ``find`` returns the value registered for ``type(node)``. A class without its own
    registration inherits the value of the nearest registered base class: a value registered
    for ``PatternElement`` also serves ``NodePattern`` when ``NodePattern`` has none. ``None``
    cannot be registered, because it reports that nothing matched. The table cannot change
    after construction.
    """

    __slots__ = ("_entries",)

    def __init__(self, entries: Mapping[type[AstNode], T]) -> None:
        self._entries: Mapping[type[AstNode], T] = MappingProxyType(dict(entries))

    def find(self, node: AstNode) -> T | None:
        """Return the value registered for the node's class or the nearest registered base class."""
        for node_type in type(node).__mro__:
            value = self._entries.get(node_type)
            if value is not None:
                return value
        return None


__all__ = ["TypeRegistry"]

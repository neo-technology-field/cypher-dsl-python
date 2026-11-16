"""Child fragments handed from a node's children to its renderer."""

from __future__ import annotations

from dataclasses import dataclass

from cypher_dsl.syntax import AstNode


@dataclass(frozen=True, weakref_slot=True, slots=True)
class Fragment:
    """Rendered text for one child, together with the node that produced it."""

    node: AstNode
    text: str


__all__ = ["Fragment"]

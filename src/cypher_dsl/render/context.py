"""Read-only inputs one construct renderer receives."""

from __future__ import annotations

from dataclasses import dataclass

from cypher_dsl.render.layout import COMPACT, Layout
from cypher_dsl.ast import OccurrenceFacts


@dataclass(frozen=True, weakref_slot=True, slots=True)
class RenderContext:
    """Immutable formatting options, the layout and the current occurrence's analysis facts."""

    always_escape_names: bool
    facts: OccurrenceFacts
    layout: Layout = COMPACT


__all__ = ["RenderContext"]

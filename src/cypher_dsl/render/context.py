"""Read-only inputs one construct renderer receives."""

from __future__ import annotations

from dataclasses import dataclass

from cypher_dsl.syntax import OccurrenceFacts


@dataclass(frozen=True, weakref_slot=True, slots=True)
class RenderContext:
    """Immutable formatting options and the current occurrence's analysis facts."""

    always_escape_names: bool
    facts: OccurrenceFacts


__all__ = ["RenderContext"]

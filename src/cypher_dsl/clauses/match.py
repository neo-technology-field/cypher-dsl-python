"""
``MATCH`` and ``OPTIONAL MATCH`` clauses with an attached filter.

``WHERE`` is not a free-standing clause here. Its meaning depends on the clause it
follows, so it is stored inside that clause and rendered immediately after it. That is
also why a second filter on the same clause has to combine with the first instead of
producing a second ``WHERE``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cypher_dsl.clauses.base import Clause
from cypher_dsl.errors import DslError, EmptyPatternError
from cypher_dsl.expressions.operators import Condition
from cypher_dsl.patterns.nodes import PatternElement, require_explicit_properties
from cypher_dsl.ast import AstNode, _require_tuple

if TYPE_CHECKING:
    from cypher_dsl.statements.builder import StatementBuilder


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class Where(AstNode):
    """
    A predicate attached to the clause that owns it.

    Attributes:
        predicate: Condition the owning clause must satisfy.
    """

    predicate: Condition

    def children(self) -> tuple[AstNode, ...]:
        """Expose the predicate as the only child."""
        return (self.predicate,)


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class MatchClause(Clause):
    """
    A pattern-matching clause with no clause between it and its filter.

    Attributes:
        patterns: Pattern elements in rendered order. At least one is required.
        optional: Whether the match may fail without removing the row.
        where: Filter owned by this clause, or ``None``.
    """

    patterns: tuple[PatternElement, ...]
    optional: bool = False
    where: Where | None = None

    def __post_init__(self) -> None:
        """
        Reject an empty or unsupported pattern list.

        Raises:
            EmptyPatternError: If no pattern is present.
            DslError: If an element is not a pattern element, or carries a whole-map
                expression where ``MATCH`` requires explicit property entries.
        """
        _require_tuple(self.patterns, "MATCH patterns")
        if not self.patterns:
            raise EmptyPatternError("MATCH requires at least one pattern.")
        for pattern in self.patterns:
            if not isinstance(pattern, PatternElement):
                raise DslError(f"MATCH accepts pattern elements, not {type(pattern).__name__}.")
            require_explicit_properties(pattern, "MATCH", "Use explicit property entries or map_() in the pattern.")

    def children(self) -> tuple[AstNode, ...]:
        """Expose the patterns, followed by the filter when one is attached."""
        return self.patterns if self.where is None else (*self.patterns, self.where)

    def with_where(self, predicate: Condition) -> MatchClause:
        """
        Return a copy whose single attached filter also requires ``predicate``.

        Consecutive filters join with ``AND`` because Cypher has one filter position
        here. Returning a copy keeps every other clause value shareable.

        Args:
            predicate: Additional condition.

        Returns:
            A new clause with one combined filter.
        """
        combined = predicate if self.where is None else self.where.predicate & predicate
        return MatchClause(self.patterns, self.optional, Where(combined))


def match(*patterns: PatternElement) -> StatementBuilder:
    """
    Start a statement with a ``MATCH`` clause.

    Args:
        patterns: One or more pattern elements in rendered order.

    Returns:
        A new builder whose only clause is ``MATCH``.

    Raises:
        EmptyPatternError: If no pattern is supplied.
        DslError: If a pattern list entry is not a pattern element or uses the
            whole-map property form.
    """
    from cypher_dsl.statements.builder import StatementBuilder

    return StatementBuilder().match(*patterns)


def optional_match(*patterns: PatternElement) -> StatementBuilder:
    """
    Start a statement with an ``OPTIONAL MATCH`` clause.

    A filter attached to this clause stays on the optional match, so the clause cannot
    remove rows it did not introduce.

    Args:
        patterns: One or more pattern elements in rendered order.

    Returns:
        A new builder whose only clause is ``OPTIONAL MATCH``.

    Raises:
        EmptyPatternError: If no pattern is supplied.
        DslError: If a pattern list entry is not a pattern element or uses the
            whole-map property form.
    """
    from cypher_dsl.statements.builder import StatementBuilder

    return StatementBuilder().optional_match(*patterns)


__all__ = ["MatchClause", "Where", "match", "optional_match"]

"""
Projection clauses and the modifiers each projection owns.

``WITH`` and ``RETURN`` share one projection body: at least one item, optional
``DISTINCT``, one ordering list and a single ``SKIP`` and ``LIMIT`` position. One
definition means the two clauses cannot render different grammar.

``WITH`` adds a filter, which Cypher places after the ordering and pagination modifiers.
Storing the filter inside the clause, rather than as a free-standing node, is what keeps
the clause sequence immutable and the rendered order fixed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, TypeAlias

from cypher_dsl.clauses.base import Clause
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.base import Expression, require_operand
from cypher_dsl.expressions.functions import Asterisk, RawExpression
from cypher_dsl.expressions.operators import Condition
from cypher_dsl.expressions.values import AliasedExpression, Literal, SortItem, Variable
from cypher_dsl.ast import AstNode, _require_tuple

if TYPE_CHECKING:
    from cypher_dsl.clauses.match import Where

OrderItem: TypeAlias = Expression | SortItem


def _validate_pagination(value: Expression | None, keyword: str) -> None:
    """
    Reject a pagination value that cannot be a row count.

    A literal has to be a whole number that is not negative. Booleans are excluded
    explicitly because Python treats them as integers and ``LIMIT true`` has no meaning.
    Parameters and computed expressions are accepted unchanged: their runtime value is
    decided by the caller or the server, and guessing it here would reject valid
    statements.

    Args:
        value: Expression attached to the pagination position, or ``None``.
        keyword: ``SKIP`` or ``LIMIT``, used in the failure message.

    Raises:
        DslError: If the value is not an expression, or a literal that is not a
            non-negative integer.
    """
    if value is None:
        return
    if not isinstance(value, Expression):
        raise DslError(f"{keyword} needs an expression, not {type(value).__name__}.")
    require_operand(value)
    if not isinstance(value, Literal):
        return
    bound = value.value
    if isinstance(bound, bool) or not isinstance(bound, int):
        raise DslError(
            f"{keyword} requires a non-negative integer literal, not {type(bound).__name__}. "
            "Bind a runtime value with param() instead."
        )
    if bound < 0:
        raise DslError(f"{keyword} requires a non-negative integer; got {bound}.")


def _validate_order_items(items: tuple[OrderItem, ...]) -> None:
    """Reject an ordering item that is neither a sort node nor an expression."""
    for item in items:
        if isinstance(item, SortItem):
            continue
        if not isinstance(item, Expression):
            raise DslError(f"ORDER BY items must be expressions or sort items, not {type(item).__name__}.")
        require_operand(item)


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class ProjectionClause(Clause):
    """
    The projection body shared by ``WITH`` and ``RETURN``.

    Attributes:
        expressions: Ordered projection items. At least one is required.
        distinct: Whether the projection removes duplicate rows.
        order_by: Ordering items in rendered order. Explicit ``asc`` and ``desc``
            produce sort nodes; a bare expression stays ascending without an ``ASC``
            token.
        skip: Rows to discard before returning results, or ``None``.
        limit: Maximum rows to return, or ``None``.
    """

    keyword: ClassVar[str] = ""

    expressions: tuple[Expression, ...]
    distinct: bool = False
    order_by: tuple[OrderItem, ...] = ()
    skip: Expression | None = None
    limit: Expression | None = None

    def __post_init__(self) -> None:
        """
        Reject an empty projection or a modifier that cannot be rendered.

        Raises:
            DslError: If the shared body is constructed directly, a collection is not
                a tuple, there is no projection item, an item is not an expression,
                ``distinct`` is not a boolean, or a pagination value is invalid.
        """
        if type(self) is ProjectionClause:
            raise DslError(
                "ProjectionClause is the shared projection body. Construct a WithClause or ReturnClause instead."
            )
        _require_tuple(self.expressions, "Projection expressions")
        _require_tuple(self.order_by, "Projection order_by")
        if not self.expressions:
            raise DslError(f"{self.keyword} requires at least one projection item.")
        for expression in self.expressions:
            if not isinstance(expression, Expression):
                raise DslError(f"A projection item must be an expression, not {type(expression).__name__}.")
        if not isinstance(self.distinct, bool):
            raise DslError(f"DISTINCT is a boolean choice, not {type(self.distinct).__name__}.")
        _validate_order_items(self.order_by)
        _validate_pagination(self.skip, "SKIP")
        _validate_pagination(self.limit, "LIMIT")

    def children(self) -> tuple[AstNode, ...]:
        """Expose the items and modifiers in rendered order."""
        modifiers: tuple[AstNode, ...] = (*self.order_by,)
        if self.skip is not None:
            modifiers = (*modifiers, self.skip)
        if self.limit is not None:
            modifiers = (*modifiers, self.limit)
        return (*self.expressions, *modifiers)


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class ReturnClause(ProjectionClause):
    """
    A ``RETURN`` clause that ends a read statement.

    ``RETURN`` carries no filter of its own. A filter belongs to the matching or
    ``WITH`` clause that precedes it. Unlike ``WITH``, ``RETURN`` may project a bare
    property or literal: the result columns only need names when a caller references
    them, not for the clause to be valid.
    """

    keyword: ClassVar[str] = "RETURN"


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class WithClause(ProjectionClause):
    """
    A ``WITH`` clause that ends one query part and starts the next.

    ``WITH`` is a scope boundary: only the names it projects are available to the clauses
    after it. Its own filter can still use incoming names as well as projected names
    unless DISTINCT or aggregation restricts it to the output. The filter renders after
    the ordering and pagination modifiers.

    Attributes:
        where: Filter owned by this clause, or ``None``.
    """

    keyword: ClassVar[str] = "WITH"

    where: Where | None = None

    def __post_init__(self) -> None:
        """
        Apply the projection checks and reject a filter node of the wrong kind.

        ``WITH`` also requires an alias for every structured projection item that is
        not a plain variable or the wildcard. Cypher accepts ``WITH m`` and ``WITH *``,
        but ``WITH 1`` or ``WITH m.title`` has no name for the next query part to use.

        Raises:
            DslError: If the projection is invalid, an item needs an alias, or ``where``
                is not a filter node.
        """
        from cypher_dsl.clauses.match import Where

        super(WithClause, self).__post_init__()
        for expression in self.expressions:
            if isinstance(expression, (Variable, RawExpression, Asterisk, AliasedExpression)):
                continue
            raise DslError(
                "WITH requires an alias for a non-variable projection item. "
                "Use .alias(name) so the projected value has a name for the next query part."
            )
        if self.where is not None and not isinstance(self.where, Where):
            raise DslError(f"WITH holds an attached filter node, not {type(self.where).__name__}.")

    def children(self) -> tuple[AstNode, ...]:
        """Expose the projection body, followed by the filter when one is attached."""
        body = super(WithClause, self).children()
        return body if self.where is None else (*body, self.where)

    def with_where(self, predicate: Condition) -> WithClause:
        """
        Return a copy whose single attached filter also requires ``predicate``.

        Consecutive filters join with ``AND`` because a ``WITH`` clause has one filter
        position. Returning a copy keeps every other clause value shareable.

        Args:
            predicate: Additional condition.

        Returns:
            A new clause with one combined filter.
        """
        from cypher_dsl.clauses.match import Where

        combined = predicate if self.where is None else self.where.predicate & predicate
        return WithClause(
            expressions=self.expressions,
            distinct=self.distinct,
            order_by=self.order_by,
            skip=self.skip,
            limit=self.limit,
            where=Where(combined),
        )


ProjectionOwner: TypeAlias = ReturnClause | WithClause

__all__ = ["ReturnClause", "WithClause"]

"""
Immutable statement construction.

A statement builder is a construction value that grows by returning a new value. It
stores no parameter bindings: those are collected per render, so a tree is reusable
and safe to share.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import cast

from cypher_dsl.ast import _require_tuple
from cypher_dsl.clauses.base import Clause
from cypher_dsl.clauses.call import SubqueryCallClause, _coerce_import, _finalise_subquery
from cypher_dsl.clauses.match import MatchClause
from cypher_dsl.clauses.projection import ProjectionOwner, ReturnClause, WithClause
from cypher_dsl.clauses.unwind import UnwindClause
from cypher_dsl.clauses.write import (
    Assignment,
    CreateClause,
    DeleteClause,
    LabelUpdate,
    MergeAction,
    MergeClause,
    RemoveClause,
    SetClause,
)
from cypher_dsl.errors import DslError, InvalidClauseOrderError
from cypher_dsl.expressions.base import (
    Expression,
    ExpressionInput,
    NamedExpression,
    ProjectionInput,
    coerce_expression,
)
from cypher_dsl.expressions.operators import Condition
from cypher_dsl.expressions.values import SortItem, SymbolicName, Variable, lit
from cypher_dsl.patterns.nodes import PatternElement
from cypher_dsl.statements.composition import Statement, UnionStatement
from cypher_dsl.statements.frames import ScopeFrame
from cypher_dsl.statements.rules import frame_after, validate_clause
from cypher_dsl.statements.rules.projection import validate_projection_modifiers
from cypher_dsl.statements.validation import (
    require_appendable,
    require_read_position,
    require_update_position,
)


def returning(*expressions: ProjectionInput) -> StatementBuilder:
    """
    Start a statement that projects the given expressions.

    A bare string in a projection position is a variable name. Use ``lit()`` for a
    string value, which keeps names and data separate at the call site.

    Args:
        expressions: One or more projection items. At least one is required.

    Returns:
        A new builder whose only clause is ``RETURN``.

    Raises:
        DslError: If no projection item is supplied.
    """
    return StatementBuilder().returning(*expressions)


def with_(*expressions: ProjectionInput) -> StatementBuilder:
    """
    Start a statement with a ``WITH`` projection.

    Args:
        expressions: One or more projection items. Bare strings are variable names.

    Returns:
        A new builder whose only clause is ``WITH``. It is not finalisable until a
        ``RETURN`` clause follows.

    Raises:
        DslError: If no projection item is supplied.
    """
    return StatementBuilder().with_(*expressions)


@dataclass(frozen=True, weakref_slot=True, slots=True)
class StatementBuilder:
    """
    An immutable sequence of clauses under construction.

    Attributes:
        clauses: Clauses in rendered order. Each fluent call returns a new builder,
            either with one more clause or with the clause that owns the change
            updated, instead of changing this one.
    """

    clauses: tuple[Clause, ...] = ()

    def __post_init__(self) -> None:
        """Keep in-progress syntax independent of caller-owned collections."""
        _require_tuple(self.clauses, "StatementBuilder clauses")

    def returning(self, *expressions: ProjectionInput) -> StatementBuilder:
        """
        Append a ``RETURN`` clause and return a new builder.

        Args:
            expressions: Projection items. Bare strings become variable names.

        Returns:
            A new builder ending in a non-empty ``RETURN`` clause.

        Raises:
            DslError: If no projection item is supplied, or a projection item refers to
                a name a preceding ``WITH`` discarded.
            InvalidClauseOrderError: If the statement already contains a ``RETURN`` clause.
        """
        if not expressions:
            raise DslError("RETURN requires at least one projection item.")
        if any(isinstance(clause, ReturnClause) for clause in self.clauses):
            raise InvalidClauseOrderError("RETURN must be the final clause and can appear only once in a statement.")
        items = tuple(_coerce_projection(expression) for expression in expressions)
        clause = ReturnClause(items)
        validate_clause(frame_after(self.clauses), clause)
        return StatementBuilder((*self.clauses, clause))

    def with_(self, *expressions: ProjectionInput) -> StatementBuilder:
        """
        Append a ``WITH`` clause and return a new builder.

        ``WITH`` ends the current query part. Only the names it projects are available
        to the clauses that follow, which is why a projection item needs a name: a plain
        variable or an alias on any structured expression.

        Args:
            expressions: Projection items. Bare strings become variable names.

        Returns:
            A new builder ending in a non-empty ``WITH`` clause.

        Raises:
            DslError: If no projection item is supplied, or a projection item refers to
                a name a preceding ``WITH`` discarded.
            InvalidClauseOrderError: If the statement already ends in ``RETURN``.
        """
        if not expressions:
            raise DslError("WITH requires at least one projection item.")
        require_appendable(self.clauses, "WITH")
        items = tuple(_coerce_projection(expression) for expression in expressions)
        clause = WithClause(items)
        validate_clause(frame_after(self.clauses), clause)
        return StatementBuilder((*self.clauses, clause))

    def match(self, *patterns: PatternElement) -> StatementBuilder:
        """
        Append a ``MATCH`` clause and return a new builder.

        Args:
            patterns: One or more pattern elements. At least one is required.

        Returns:
            A new builder ending in a ``MATCH`` clause. It is not finalisable until a
            ``RETURN`` clause follows.

        Raises:
            EmptyPatternError: If no pattern is supplied.
            DslError: If a pattern is not a pattern element or uses the whole-map
                property form.
            InvalidClauseOrderError: If the statement already ends in ``RETURN``.
        """
        return self._with_pattern_clause(patterns, optional=False)

    def optional_match(self, *patterns: PatternElement) -> StatementBuilder:
        """
        Append an ``OPTIONAL MATCH`` clause and return a new builder.

        Args:
            patterns: One or more pattern elements. At least one is required.

        Returns:
            A new builder ending in an ``OPTIONAL MATCH`` clause.

        Raises:
            EmptyPatternError: If no pattern is supplied.
            DslError: If a pattern is not a pattern element or uses the whole-map
                property form.
            InvalidClauseOrderError: If the statement already ends in ``RETURN``.
        """
        return self._with_pattern_clause(patterns, optional=True)

    def unwind(self, values: ExpressionInput, variable: Variable) -> StatementBuilder:
        """
        Append an ``UNWIND`` clause and return a new builder.

        ``UNWIND`` is a reading clause that adds one row per element and binds
        ``variable`` for the clauses that follow. It cannot filter: a caller who needs a
        predicate adds ``with_()`` first, because ``WHERE`` belongs to ``MATCH`` or
        ``WITH``.

        Args:
            values: Collection expression or literal data to iterate.
            variable: Variable bound to the current element.

        Returns:
            A new builder ending in an ``UNWIND`` clause. It is not finalisable until a
            ``RETURN`` or a write clause follows.

        Raises:
            DslError: If the target is not a variable or the value cannot be an
                expression.
            InvalidClauseOrderError: If the statement ends in ``RETURN``, or an updating
                clause in the same query part has no ``WITH`` boundary before it.
        """
        require_read_position(self.clauses, "UNWIND")
        clause = UnwindClause(coerce_expression(values), variable)
        validate_clause(frame_after(self.clauses), clause)
        return StatementBuilder((*self.clauses, clause))

    def call(
        self,
        subquery: Statement | UnionStatement | StatementBuilder,
        imports: tuple[str | Variable, ...] = (),
        import_all: bool = False,
        in_transactions: bool | ExpressionInput = False,
    ) -> StatementBuilder:
        """
        Append a ``CALL`` subquery clause and return a new builder.

        The call renders the variable scope clause and runs the body once per incoming
        row. The body sees outer variables only through ``imports`` or ``import_all``,
        and the names its final ``RETURN`` projects become available to the clauses
        after the call.

        Args:
            subquery: Finalised statement, union or builder for the body.
            imports: Outer variables the scope clause passes into the body. A bare
                string is a variable name.
            import_all: Render ``(*)`` and pass every outer variable into the body.
            in_transactions: Run the body in separate inner transactions. ``True``
                renders the bare modifier. A positive integer literal, parameter or
                expression renders ``OF ... ROWS``.

        Returns:
            A new builder ending in the ``CALL`` clause.

        Raises:
            DslError: If the body is not finalisable, an import is not a variable name,
                named imports and ``import_all`` are combined, or the row count is
                invalid.
            InvalidClauseOrderError: If the statement already ends in ``RETURN``, or an
                updating clause in the current query part has no ``WITH`` boundary in
                front of the call.
        """
        return self._with_subquery_call(subquery, imports, import_all, False, in_transactions)

    def optional_call(
        self,
        subquery: Statement | UnionStatement | StatementBuilder,
        imports: tuple[str | Variable, ...] = (),
        import_all: bool = False,
        in_transactions: bool | ExpressionInput = False,
    ) -> StatementBuilder:
        """
        Append an ``OPTIONAL CALL`` subquery clause and return a new builder.

        Rows the body produces no output for survive with ``null`` bindings, the same
        way ``OPTIONAL MATCH`` keeps rows without a match.

        Args:
            subquery: Finalised statement, union or builder for the body.
            imports: Outer variables the scope clause passes into the body.
            import_all: Render ``(*)`` and pass every outer variable into the body.
            in_transactions: Run the body in separate inner transactions. ``True``
                renders the bare modifier. A positive integer literal, parameter or
                expression renders ``OF ... ROWS``.

        Returns:
            A new builder ending in the ``OPTIONAL CALL`` clause.

        Raises:
            DslError: If the body is not finalisable, an import is not a variable name,
                named imports and ``import_all`` are combined, or the row count is
                invalid.
            InvalidClauseOrderError: If the statement already ends in ``RETURN``, or an
                updating clause in the current query part has no ``WITH`` boundary in
                front of the call.
        """
        return self._with_subquery_call(subquery, imports, import_all, True, in_transactions)

    def _with_subquery_call(
        self,
        subquery: Statement | UnionStatement | StatementBuilder,
        imports: tuple[str | Variable, ...],
        import_all: bool,
        optional: bool,
        in_transactions: bool | ExpressionInput,
    ) -> StatementBuilder:
        require_read_position(self.clauses, "CALL")
        finalised = _finalise_subquery(subquery)
        coerced = tuple(_coerce_import(item) for item in imports)
        if in_transactions is True or in_transactions is False:
            modifier = in_transactions
            rows = None
        else:
            modifier = True
            rows = coerce_expression(in_transactions)
        clause = SubqueryCallClause(finalised, coerced, import_all, optional, modifier, rows)
        validate_clause(frame_after(self.clauses), clause)
        return StatementBuilder((*self.clauses, clause))

    def create(self, *patterns: PatternElement) -> StatementBuilder:
        """
        Append a ``CREATE`` clause and return a new builder.

        ``CREATE`` may start a statement or follow a read or another write. A whole-map
        expression is accepted as pattern properties here because the server reads the
        map while it creates the element.

        Args:
            patterns: One or more pattern elements. At least one is required.

        Returns:
            A new builder ending in a ``CREATE`` clause. It is finalisable without a
            ``RETURN``.

        Raises:
            EmptyPatternError: If no pattern is supplied.
            DslError: If a pattern is not a pattern element.
            InvalidClauseOrderError: If the statement already ends in ``RETURN``.
        """
        require_appendable(self.clauses, "CREATE")
        clause = CreateClause(patterns)
        validate_clause(frame_after(self.clauses), clause)
        return StatementBuilder((*self.clauses, clause))

    def merge(self, pattern: PatternElement) -> StatementBuilder:
        """
        Append a ``MERGE`` clause and return a new builder.

        The identity is the single pattern. It is never inferred from the update
        properties that follow, so callers have to state what the server should search
        for.

        Args:
            pattern: The pattern to match or create.

        Returns:
            A new builder ending in a ``MERGE`` clause. It is finalisable without a
            ``RETURN``.

        Raises:
            DslError: If the argument is not a pattern element or uses a whole-map
                property expression.
            InvalidClauseOrderError: If the statement already ends in ``RETURN``.
        """
        require_appendable(self.clauses, "MERGE")
        clause = MergeClause(pattern)
        validate_clause(frame_after(self.clauses), clause)
        return StatementBuilder((*self.clauses, clause))

    def on_create(self, *updates: Assignment) -> StatementBuilder:
        """
        Attach an ``ON CREATE`` action to the merge that immediately precedes it.

        Args:
            updates: Assignments applied when the merge creates the pattern. At least one
                is required.

        Returns:
            A new builder whose merge owns the action.

        Raises:
            DslError: If no update is supplied, or the merge already has an
                ``ON CREATE`` action.
            InvalidClauseOrderError: If the final clause is not a ``MERGE``.
        """
        return self._with_merge_action("ON CREATE", updates)

    def on_match(self, *updates: Assignment) -> StatementBuilder:
        """
        Attach an ``ON MATCH`` action to the merge that immediately precedes it.

        Args:
            updates: Assignments applied when the merge matches the pattern. At least one
                is required.

        Returns:
            A new builder whose merge owns the action.

        Raises:
            DslError: If no update is supplied, or the merge already has an
                ``ON MATCH`` action.
            InvalidClauseOrderError: If the final clause is not a ``MERGE``.
        """
        return self._with_merge_action("ON MATCH", updates)

    def set_(self, *updates: Assignment | LabelUpdate) -> StatementBuilder:
        """
        Append a ``SET`` clause and return a new builder.

        Args:
            updates: Property assignments and label updates. At least one is required.

        Returns:
            A new builder ending in a ``SET`` clause. It is finalisable without a
            ``RETURN``.

        Raises:
            DslError: If no update is supplied, an update is of the wrong kind, or a
                value refers to a name a preceding ``WITH`` discarded.
            InvalidClauseOrderError: If no clause precedes the update, or the statement ends
                in ``RETURN``.
        """
        if not updates:
            raise DslError("SET requires at least one update.")
        require_update_position(self.clauses, "SET")
        clause = SetClause(tuple(updates))
        validate_clause(frame_after(self.clauses), clause)
        return StatementBuilder((*self.clauses, clause))

    def remove(self, *targets: Expression | LabelUpdate) -> StatementBuilder:
        """
        Append a ``REMOVE`` clause and return a new builder.

        Args:
            targets: Property references and label updates. At least one is required.

        Returns:
            A new builder ending in a ``REMOVE`` clause. It is finalisable without a
            ``RETURN``.

        Raises:
            DslError: If no target is supplied, a target is a literal or arithmetic
                expression, or a reference was discarded by a preceding ``WITH``.
            InvalidClauseOrderError: If no clause precedes the removal, or the statement ends
                in ``RETURN``.
        """
        if not targets:
            raise DslError("REMOVE requires at least one target.")
        require_update_position(self.clauses, "REMOVE")
        clause = RemoveClause(tuple(targets))
        validate_clause(frame_after(self.clauses), clause)
        return StatementBuilder((*self.clauses, clause))

    def delete(self, *targets: ExpressionInput) -> StatementBuilder:
        """
        Append a ``DELETE`` clause and return a new builder.

        Args:
            targets: Named nodes or relationships to delete. At least one is required.

        Returns:
            A new builder ending in a ``DELETE`` clause. It is finalisable without a
            ``RETURN``.

        Raises:
            DslError: If no target is supplied, a target does not name an element, or a
                reference was discarded by a preceding ``WITH``.
            InvalidClauseOrderError: If no clause precedes the deletion, or the statement
                ends in ``RETURN``.
        """
        return self._with_delete(targets, detach=False)

    def detach_delete(self, *targets: ExpressionInput) -> StatementBuilder:
        """
        Append a ``DETACH DELETE`` clause and return a new builder.

        Args:
            targets: Named nodes or relationships to delete with their relationships. At
                least one is required.

        Returns:
            A new builder ending in a ``DETACH DELETE`` clause. It is finalisable without a
            ``RETURN``.

        Raises:
            DslError: If no target is supplied, a target does not name an element, or a
                reference was discarded by a preceding ``WITH``.
            InvalidClauseOrderError: If no clause precedes the deletion, or the statement
                ends in ``RETURN``.
        """
        return self._with_delete(targets, detach=True)

    def where(self, condition: Condition) -> StatementBuilder:
        """
        Attach a filter to the clause that immediately precedes it.

        The filter belongs to that clause, so a filter after ``OPTIONAL MATCH`` stays on
        the optional match. An ordinary ``WITH`` filter sees incoming and projected
        names, but ``DISTINCT`` and aggregation restrict it to projected names.
        Subsequent clauses always see only the output. Repeated filters combine with
        ``AND``.

        Args:
            condition: Predicate the owning clause must satisfy.

        Returns:
            A new builder whose owning clause carries the combined filter.

        Raises:
            DslError: If no clause can own a filter yet, or the predicate refers to a
                name a preceding ``WITH`` discarded.
            InvalidClauseOrderError: If the statement already ends in ``RETURN``, or the
                final clause is not a ``MATCH`` or ``WITH``. After ``UNWIND``, add
                ``with_()`` before filtering.
        """
        if not self.clauses:
            raise DslError("WHERE needs a MATCH or WITH clause to filter. Start the statement with match().")
        owner = self.clauses[-1]
        if isinstance(owner, ReturnClause):
            raise InvalidClauseOrderError("WHERE must precede RETURN in a statement.")
        if not isinstance(owner, (MatchClause, WithClause)):
            raise InvalidClauseOrderError(
                f"WHERE must follow a MATCH or WITH clause, not {type(owner).__name__}. "
                "After UNWIND, add with_() before filtering."
            )
        updated = owner.with_where(condition)
        validate_clause(_scope_before_owner(self.clauses), updated)
        return StatementBuilder((*self.clauses[:-1], updated))

    def distinct(self) -> StatementBuilder:
        """
        Mark the current projection as distinct.

        DISTINCT restricts ordering and pagination to the projected result. Marking a
        projection distinct revalidates modifiers already attached to it, so the call
        order cannot decide whether the rule applies.

        Returns:
            A new builder whose final clause carries an explicit ``DISTINCT``.

        Raises:
            DslError: If no ``WITH`` or ``RETURN`` clause owns the modifier, or an
                attached modifier refers to a name the distinct projection discards.
        """
        owner = self._projection_owner("DISTINCT")
        updated = replace(owner, distinct=True)
        validate_clause(_scope_before_owner(self.clauses), updated)
        return self._replace_owner(updated)

    def order_by(self, *items: ExpressionInput | SortItem) -> StatementBuilder:
        """
        Add ordering items to the current projection.

        Bare expressions sort ascending without an ``ASC`` token. Explicit ``asc`` and
        ``desc`` items keep their direction. Repeated calls append, because ordering
        items are additive and a second call does not contradict the first.

        Args:
            items: One or more expressions or sort items.

        Returns:
            A new builder whose projection carries the combined ordering.

        Raises:
            DslError: If no item is supplied, no projection owns the modifier, or an
                item refers to a name a preceding ``WITH`` discarded.
        """
        if not items:
            raise DslError("ORDER BY requires at least one item.")
        owner = self._projection_owner("ORDER BY")
        coerced = tuple(item if isinstance(item, SortItem) else coerce_expression(item) for item in items)
        updated = replace(owner, order_by=(*owner.order_by, *coerced))
        validate_projection_modifiers(_scope_before_owner(self.clauses), updated)
        return self._replace_owner(updated)

    def skip(self, value: int | Expression) -> StatementBuilder:
        """
        Skip rows before returning results.

        Args:
            value: A non-negative integer literal, a parameter, or an expression whose
                runtime value the server decides.

        Returns:
            A new builder whose projection carries the ``SKIP`` value.

        Raises:
            DslError: If the projection already has a ``SKIP`` value, the owner is not a
                projection, or the value is not a valid pagination expression.
        """
        owner = self._projection_owner("SKIP")
        if owner.skip is not None:
            raise DslError("SKIP is already set on this projection. A statement has one SKIP position.")
        expression = coerce_expression(value)
        updated = replace(owner, skip=expression)
        validate_projection_modifiers(_scope_before_owner(self.clauses), updated)
        return self._replace_owner(updated)

    def limit(self, value: int | Expression) -> StatementBuilder:
        """
        Limit the number of returned rows.

        Args:
            value: A non-negative integer literal, a parameter, or an expression whose
                runtime value the server decides.

        Returns:
            A new builder whose projection carries the ``LIMIT`` value.

        Raises:
            DslError: If the projection already has a ``LIMIT`` value, the owner is not a
                projection, or the value is not a valid pagination expression.
        """
        owner = self._projection_owner("LIMIT")
        if owner.limit is not None:
            raise DslError("LIMIT is already set on this projection. A statement has one LIMIT position.")
        expression = coerce_expression(value)
        updated = replace(owner, limit=expression)
        validate_projection_modifiers(_scope_before_owner(self.clauses), updated)
        return self._replace_owner(updated)

    def _with_merge_action(self, keyword: str, updates: tuple[Assignment, ...]) -> StatementBuilder:
        if not updates:
            raise DslError(f"{keyword} requires at least one assignment.")
        owner = self.clauses[-1] if self.clauses else None
        if not isinstance(owner, MergeClause):
            raise InvalidClauseOrderError(f"{keyword} must immediately follow the MERGE clause it belongs to.")
        action = MergeAction(keyword, tuple(updates))
        updated = owner.with_action(action)
        validate_clause(frame_after(self.clauses[:-1]), updated)
        return StatementBuilder((*self.clauses[:-1], updated))

    def _with_delete(self, targets: tuple[ExpressionInput, ...], detach: bool) -> StatementBuilder:
        keyword = "DETACH DELETE" if detach else "DELETE"
        if not targets:
            raise DslError(f"{keyword} requires at least one target.")
        require_update_position(self.clauses, keyword)
        # DeleteClause validates that every coerced target is a Variable, so the cast
        # records what that check proves rather than weakening the stored field type.
        clause = DeleteClause(
            cast("tuple[Variable, ...]", tuple(coerce_expression(target) for target in targets)), detach
        )
        validate_clause(frame_after(self.clauses), clause)
        return StatementBuilder((*self.clauses, clause))

    def _with_pattern_clause(self, patterns: tuple[PatternElement, ...], optional: bool) -> StatementBuilder:
        require_read_position(self.clauses, "MATCH")
        clause = MatchClause(patterns, optional)
        validate_clause(frame_after(self.clauses), clause)
        return StatementBuilder((*self.clauses, clause))

    def _projection_owner(self, action: str) -> ProjectionOwner:
        if not self.clauses:
            raise DslError(
                f"{action} needs a WITH or RETURN projection to modify. Add the projection before the modifier."
            )
        owner = self.clauses[-1]
        if not isinstance(owner, (ReturnClause, WithClause)):
            raise DslError(
                f"{action} modifies a WITH or RETURN projection, not {type(owner).__name__}. "
                "Add the projection before the modifier."
            )
        return owner

    def _replace_owner(self, owner: ProjectionOwner) -> StatementBuilder:
        return StatementBuilder((*self.clauses[:-1], owner))

    def build(self) -> Statement:
        """
        Finalise the builder into a statement a renderer accepts.

        Returns:
            A statement holding the same ordered clauses.

        Raises:
            DslError: If the builder has no clauses, or ends in a reading clause with no
                ``RETURN`` to finalise it.
            InvalidClauseOrderError: If a ``RETURN`` clause precedes the final clause.
        """
        return Statement(self.clauses)


def _coerce_projection(value: ProjectionInput) -> Expression:
    if isinstance(value, str):
        return Variable(SymbolicName(value))
    if isinstance(value, Expression):
        return value
    if isinstance(value, NamedExpression):
        return value.as_expression()
    return lit(value)


def _scope_before_owner(clauses: tuple[Clause, ...]) -> ScopeFrame:
    """Return the frame the current projection reads from."""
    return frame_after(clauses[:-1])


__all__ = [
    "StatementBuilder",
    "returning",
    "with_",
]

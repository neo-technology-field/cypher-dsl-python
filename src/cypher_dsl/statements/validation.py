"""
Checks that reject an invalid clause sequence before a renderer sees it.

A clause is checked against the scope in front of it, and a projection is rechecked when
a modifier replaces it. The checks cover clause order, known references and binding
declarations, not server-side semantics.
"""

from __future__ import annotations

from collections.abc import Sequence

from cypher_dsl.clauses.base import Clause
from cypher_dsl.clauses.projection import ProjectionClause, ReturnClause, WithClause
from cypher_dsl.clauses.write import CreateClause, DeleteClause, MergeClause, RemoveClause, SetClause
from cypher_dsl.errors import DslError, InvalidClauseOrderError
from cypher_dsl.expressions.base import Expression
from cypher_dsl.expressions.functions import Asterisk, FunctionInvocation, RawExpression
from cypher_dsl.expressions.values import AliasedExpression, SortItem, Variable
from cypher_dsl.patterns.nodes import PatternElement
from cypher_dsl.statements.scope import (
    _merge_names,
    _pattern_bindings,
    _pattern_property_references,
    _reference_names,
    _Scope,
    _scope_after_clause,
    _variables_in,
    classify_write_declarations,
)
from cypher_dsl.syntax import AstNode, structurally_equal

# Clauses that change the graph. They can end a statement without a RETURN, and once one
# appears in the current query part a further MATCH needs a WITH boundary.
_UPDATE_CLAUSES = (CreateClause, MergeClause, SetClause, RemoveClause, DeleteClause)


# Aggregates that collapse the incoming row before ORDER BY or pagination applies.
# The set is used only to decide whether a projection keeps the incoming scope. It is
# deliberately small and is not a function catalogue: an unknown name is treated as an
# ordinary function, which keeps the broader input-plus-output ordering rule.
_AGGREGATE_FUNCTIONS = frozenset(
    {
        "avg",
        "collect",
        "count",
        "max",
        "min",
        "percentilecont",
        "percentiledisc",
        "stdev",
        "stdevp",
        "sum",
    }
)


def _current_part_has_update(clauses: tuple[Clause, ...]) -> bool:
    """
    Return whether the current query part already contains an updating clause.

    A ``WITH`` starts a new part, so a read after it is allowed. Reading again in the
    same part after a write is not part of the grammar.
    """
    for clause in reversed(clauses):
        if isinstance(clause, WithClause):
            return False
        if isinstance(clause, _UPDATE_CLAUSES):
            return True
    return False


def _require_update_position(clauses: tuple[Clause, ...], keyword: str) -> None:
    """
    Reject an update that has nothing to modify or that follows ``RETURN``.

    A ``SET``, ``REMOVE`` or deletion cannot introduce the element it writes. Those
    clauses therefore need an earlier clause, while ``CREATE`` and ``MERGE`` can start a
    statement.
    """
    if clauses and isinstance(clauses[-1], ReturnClause):
        raise InvalidClauseOrderError(f"{keyword} must precede RETURN in a statement.")
    if not clauses:
        raise InvalidClauseOrderError(
            f"{keyword} needs a preceding clause that binds its target. Start with match(), create() or merge()."
        )


def _validate_write_declarations(scope: _Scope, patterns: tuple[PatternElement, ...], keyword: str) -> None:
    """Reject invalid write declarations through the shared classification rules."""
    classify_write_declarations(scope, patterns, keyword)


def _contains_raw(node: AstNode) -> bool:
    """Return whether a trusted raw expression appears anywhere in a tree."""
    if isinstance(node, RawExpression):
        return True
    return any(_contains_raw(child) for child in node.children())


def _is_aggregate_call(node: AstNode) -> bool:
    """Return whether a node is a call to one of the known aggregate functions."""
    if not isinstance(node, FunctionInvocation):
        return False
    if len(node.function_name) != 1:
        return False
    return node.function_name[0].lower() in _AGGREGATE_FUNCTIONS


def _contains_aggregate(node: AstNode) -> bool:
    """Return whether a projection expression contains a known aggregate."""
    if _is_aggregate_call(node):
        return True
    return any(_contains_aggregate(child) for child in node.children())


def _modifier_scope(scope: _Scope, clause: ProjectionClause) -> tuple[str, ...] | None:
    """
    Return the names an ordering, pagination or owning WITH filter may reference.

    An ordinary projection keeps both the incoming names and the names it creates, so a
    discarded name is still rejected while an unaliased property or literal does not
    make the incoming scope unknowable. A ``DISTINCT`` or aggregating projection collapses
    the input first, so its modifiers may only use the projected names themselves. That
    rule does not need an incoming scope, which is what makes it apply to the first
    ``WITH`` as well. An item without an output name contributes no name, and the exact
    projected expression is still accepted as an ``ORDER BY`` item by
    :func:`_validate_projection_modifiers`. Trusted raw syntax always leaves the result
    unknown.
    """
    if any(_contains_raw(expression) for expression in clause.expressions):
        return None
    restricting = clause.distinct or any(_contains_aggregate(expression) for expression in clause.expressions)
    names: list[str] = []
    if restricting:
        for expression in clause.expressions:
            if isinstance(expression, Asterisk):
                if scope.names is None:
                    return None
                names.extend(scope.names)
            elif isinstance(expression, AliasedExpression):
                names.append(expression.alias_name.value)
            elif isinstance(expression, Variable):
                names.append(expression.symbol.value)
            elif isinstance(expression, RawExpression):
                return None
        return _merge_names(tuple(names))
    if not scope.closed or scope.names is None:
        return None
    names.extend(scope.names)
    for expression in clause.expressions:
        if isinstance(expression, Asterisk):
            continue
        if isinstance(expression, AliasedExpression):
            names.append(expression.alias_name.value)
        elif isinstance(expression, Variable):
            names.append(expression.symbol.value)
    return _merge_names(tuple(names))


def _validate_projection_modifiers(scope: _Scope, clause: ProjectionClause) -> None:
    """
    Check ordering and pagination references against the projection they modify.

    An expression that is itself projected is allowed even when it has no output name,
    which is what keeps ``ORDER BY m.title`` valid for ``RETURN m.title``. A restricting
    projection additionally limits every other reference to its projected names.
    """
    if not clause.order_by and clause.skip is None and clause.limit is None:
        return
    allowed = _modifier_scope(scope, clause)
    if allowed is None:
        return
    projected = tuple(
        expression.expression if isinstance(expression, AliasedExpression) else expression
        for expression in clause.expressions
        if not isinstance(expression, (Asterisk, RawExpression))
    )
    _validate_modifier_references(clause.order_by, allowed, projected, "ORDER BY", allow_projected=True)
    for keyword, value in (("SKIP", clause.skip), ("LIMIT", clause.limit)):
        if value is not None:
            _validate_modifier_references((value,), allowed, projected, keyword, allow_projected=False)


def _validate_modifier_references(
    expressions: Sequence[AstNode],
    names: tuple[str, ...],
    projected: tuple[Expression, ...],
    construct: str,
    allow_projected: bool,
) -> None:
    """
    Validate modifier references, stopping at subtrees the projection already contains.

    ``ORDER BY`` has the documented rule that an ordering expression must appear in a
    ``DISTINCT`` or aggregating projection. A projected subtree is therefore a value the
    modifier may reuse, including a property or aggregate that appears inside a larger
    computed ordering expression. Walking stops at such a subtree because its own
    variables are already accounted for by the projection. A reference outside every
    projected subtree is still checked against the available names, so a projected
    sibling does not exempt a discarded input property. ``SKIP`` and ``LIMIT`` only read
    the names available after the projection, so they use the plain reference check.
    """
    for expression in expressions:
        target = expression.expression if isinstance(expression, SortItem) else expression
        if not allow_projected:
            _validate_known_references((expression,), names, construct)
            continue
        _validate_expression_references(target, names, projected, construct)


def _validate_expression_references(
    node: AstNode,
    names: tuple[str, ...],
    projected: tuple[Expression, ...],
    construct: str,
) -> None:
    """Check one expression, treating a structurally projected subtree as available."""
    if any(structurally_equal(node, candidate) for candidate in projected):
        return
    if isinstance(node, Variable):
        _validate_known_references((node,), names, construct)
        return
    for child in node.children():
        _validate_expression_references(child, names, projected, construct)


def _validate_clause(scope_before: _Scope, clause: Clause) -> None:
    """
    Validate one clause against the scope in front of it.

    The same function serves the fluent construction calls and the final statement
    walk. A projection validates its items and attached modifiers. A matching clause
    validates the property expressions inside its patterns against its own bindings as
    well as the names already available.
    """
    from cypher_dsl.clauses.match import MatchClause
    from cypher_dsl.clauses.unwind import UnwindClause

    if isinstance(clause, (CreateClause, MergeClause)):
        patterns = (clause.pattern,) if isinstance(clause, MergeClause) else clause.patterns
        _validate_write_declarations(scope_before, patterns, "MERGE" if isinstance(clause, MergeClause) else "CREATE")
    if isinstance(clause, ProjectionClause):
        _validate_known_references(clause.expressions, _reference_names(scope_before), clause.keyword)
        _validate_projection_modifiers(scope_before, clause)
    elif isinstance(clause, UnwindClause):
        _validate_known_references((clause.values,), _reference_names(scope_before), "UNWIND")
    elif isinstance(clause, MatchClause) and scope_before.closed and scope_before.names is not None:
        available = _merge_names(scope_before.names, _pattern_bindings(clause.patterns))
        _validate_known_references(
            _pattern_property_references(clause.patterns),
            available,
            "MATCH pattern properties",
        )
    elif isinstance(clause, CreateClause) and scope_before.closed and scope_before.names is not None:
        available = _merge_names(scope_before.names, _pattern_bindings(clause.patterns))
        _validate_known_references(
            _pattern_property_references(clause.patterns), available, "CREATE pattern properties"
        )
    elif isinstance(clause, MergeClause) and scope_before.closed and scope_before.names is not None:
        available = _merge_names(scope_before.names, _pattern_bindings((clause.pattern,)))
        _validate_known_references(
            _pattern_property_references((clause.pattern,)),
            available,
            "MERGE pattern properties",
        )
        for action in clause.actions:
            _validate_known_references(action.updates, available, action.keyword)
    elif isinstance(clause, SetClause):
        _validate_known_references(clause.updates, _reference_names(scope_before), "SET")
    elif isinstance(clause, RemoveClause):
        _validate_known_references(clause.targets, _reference_names(scope_before), "REMOVE")
    elif isinstance(clause, DeleteClause):
        _validate_known_references(clause.targets, _reference_names(scope_before), "DELETE")
    if isinstance(clause, WithClause) and clause.where is not None:
        _validate_known_references((clause.where.predicate,), _modifier_scope(scope_before, clause), "WHERE")
    elif isinstance(clause, MatchClause) and clause.where is not None:
        _validate_known_references(
            (clause.where.predicate,), _reference_names(_scope_after_clause(scope_before, clause)), "WHERE"
        )


def _validate_known_references(expressions: Sequence[AstNode], names: tuple[str, ...] | None, construct: str) -> None:
    """
    Reject a reference to a name the available scope does not contain.

    This is structural checking, not full semantic analysis. It runs only when the
    caller has a name list to check against, and only for variables the expression tree
    actually contains.
    """
    if names is None:
        return
    for expression in expressions:
        for variable in _variables_in(expression):
            if variable.symbol.value not in names:
                raise DslError(
                    f"{construct} refers to {variable.symbol.value!r}, which is not in scope. "
                    "A WITH clause keeps only the names it projects. "
                    "Project the name or alias the value before referring to it."
                )


def _validate_statement_clauses(clauses: tuple[Clause, ...]) -> None:
    from cypher_dsl.clauses.match import MatchClause
    from cypher_dsl.clauses.unwind import UnwindClause

    if not clauses:
        raise DslError("A statement needs at least one clause before it can be rendered.")
    if any(isinstance(clause, ReturnClause) for clause in clauses[:-1]):
        raise InvalidClauseOrderError("RETURN must be the final clause and can appear only once in a statement.")
    for index, clause in enumerate(clauses):
        if isinstance(clause, SetClause):
            _require_update_position(clauses[:index], "SET")
        elif isinstance(clause, RemoveClause):
            _require_update_position(clauses[:index], "REMOVE")
        elif isinstance(clause, DeleteClause):
            _require_update_position(clauses[:index], "DETACH DELETE" if clause.detach else "DELETE")
        elif isinstance(clause, (MatchClause, UnwindClause)) and _current_part_has_update(clauses[:index]):
            raise InvalidClauseOrderError(
                f"{'MATCH' if isinstance(clause, MatchClause) else 'UNWIND'} after an updating clause "
                "needs a WITH boundary. Add with_() before reading again."
            )
    if not isinstance(clauses[-1], (ReturnClause, *_UPDATE_CLAUSES)):
        raise DslError(
            "A statement must end with a RETURN clause or a write clause. A read that stops at MATCH is incomplete."
        )
    _validate_clause_scopes(clauses)


def _validate_clause_scopes(clauses: tuple[Clause, ...]) -> None:
    """
    Apply the derived scope to every clause of a statement.

    Running the check here means a directly constructed statement is validated by the
    same rules as a statement reached through the fluent builder.
    """
    scope = _Scope(())
    for clause in clauses:
        _validate_clause(scope, clause)
        scope = _scope_after_clause(scope, clause)

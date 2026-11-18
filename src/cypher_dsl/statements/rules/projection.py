"""The projection rule: output names, retained node identities and modifier references."""

from __future__ import annotations

from collections.abc import Sequence

from cypher_dsl.ast import AstNode, structurally_equal
from cypher_dsl.clauses.projection import ProjectionClause, WithClause
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.base import Expression
from cypher_dsl.expressions.functions import Asterisk, FunctionInvocation, RawExpression
from cypher_dsl.expressions.values import AliasedExpression, SortItem, Variable
from cypher_dsl.patterns.nodes import NodePattern
from cypher_dsl.statements.frames import ScopeFrame, is_unresolved_node, merge_names, reference_names
from cypher_dsl.statements.rules.base import SemanticRule, check_references

# Aggregates that collapse the incoming row before ORDER BY or pagination applies.
# The set is used only to decide whether a projection keeps the incoming names. It is
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


def _modifier_scope(frame: ScopeFrame, clause: ProjectionClause) -> tuple[str, ...] | None:
    """
    Return the names an ordering, pagination or owning WITH filter may reference.

    An ordinary projection keeps both the incoming names and the names it creates, so a
    discarded name is still rejected while an unaliased property or literal does not
    make the incoming names unknowable. A ``DISTINCT`` or aggregating projection collapses
    the input first, so its modifiers may only use the projected names themselves. That
    rule does not need an incoming frame, which is what makes it apply to the first
    ``WITH`` as well. An item without an output name contributes no name, and the exact
    projected expression is still accepted as an ``ORDER BY`` item by
    :func:`validate_projection_modifiers`. Trusted raw syntax always leaves the result
    unknown.
    """
    if any(_contains_raw(expression) for expression in clause.expressions):
        return None
    restricting = clause.distinct or any(_contains_aggregate(expression) for expression in clause.expressions)
    names: list[str] = []
    if restricting:
        for expression in clause.expressions:
            if isinstance(expression, Asterisk):
                if frame.names is None:
                    return None
                names.extend(frame.names)
            elif isinstance(expression, AliasedExpression):
                names.append(expression.alias_name.value)
            elif isinstance(expression, Variable):
                names.append(expression.symbol.value)
            elif isinstance(expression, RawExpression):
                return None
        return merge_names(tuple(names))
    if not frame.closed or frame.names is None:
        return None
    names.extend(frame.names)
    for expression in clause.expressions:
        if isinstance(expression, Asterisk):
            continue
        if isinstance(expression, AliasedExpression):
            names.append(expression.alias_name.value)
        elif isinstance(expression, Variable):
            names.append(expression.symbol.value)
    return merge_names(tuple(names))


def validate_projection_modifiers(frame: ScopeFrame, clause: ProjectionClause) -> None:
    """
    Check ordering and pagination references against the projection they modify.

    An expression that is itself projected is allowed even when it has no output name,
    which is what keeps ``ORDER BY m.title`` valid for ``RETURN m.title``. A restricting
    projection additionally limits every other reference to its projected names.
    """
    if not clause.order_by and clause.skip is None and clause.limit is None:
        return
    allowed = _modifier_scope(frame, clause)
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
            check_references((expression,), names, construct)
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
        check_references((node,), names, construct)
        return
    for child in node.children():
        _validate_expression_references(child, names, projected, construct)


def projection_output_names(frame: ScopeFrame, clause: ProjectionClause) -> tuple[str, ...] | None:
    """
    Return the names a projection makes available to subsequent clauses.

    A wildcard keeps the incoming names. A trusted raw projection may introduce any
    name, so it makes the result unknown rather than certifying an incomplete list.
    """
    names: list[str] = []
    for expression in clause.expressions:
        if isinstance(expression, Asterisk):
            if frame.names is None or (not frame.closed and not frame.certified):
                return None
            names.extend(frame.names)
        elif isinstance(expression, Variable):
            names.append(expression.symbol.value)
        elif isinstance(expression, AliasedExpression):
            names.append(expression.alias_name.value)
        elif isinstance(expression, RawExpression):
            return None
        else:
            return None
    return merge_names(tuple(names))


def projection_node_declarations(frame: ScopeFrame, clause: ProjectionClause) -> tuple[tuple[str, NodePattern], ...]:
    """
    Carry known node identities through retained variables and aliases only.

    A computed value with the same alias does not retain a node identity. Trusted
    raw projections remain uncertified, so they do not establish which nodes survived.
    """
    incoming = dict(frame.bindings)
    kept: dict[str, NodePattern] = {}
    for expression in clause.expressions:
        if isinstance(expression, (Asterisk, RawExpression)):
            kept.update(incoming)
        elif isinstance(expression, Variable) and expression.symbol.value in incoming:
            kept[expression.symbol.value] = incoming[expression.symbol.value]
        elif isinstance(expression, AliasedExpression):
            inner = expression.expression
            if isinstance(inner, Variable) and inner.symbol.value in incoming:
                kept[expression.alias_name.value] = incoming[inner.symbol.value]
            elif isinstance(inner, RawExpression):
                kept.update(incoming)
    return tuple(kept.items())


def _projection_unresolved_nodes(frame: ScopeFrame, clause: ProjectionClause) -> frozenset[str]:
    """Retain projected variables whose possible imported node declarations are not known yet."""
    unresolved: list[str] = []
    for expression in clause.expressions:
        if isinstance(expression, (Asterisk, RawExpression)):
            unresolved.extend(frame.unresolved)
            continue
        inner = expression.expression if isinstance(expression, AliasedExpression) else expression
        if not isinstance(inner, Variable):
            continue
        name = inner.symbol.value
        if is_unresolved_node(frame, name):
            unresolved.append(expression.alias_name.value if isinstance(expression, AliasedExpression) else name)
    return frozenset(unresolved)


class ProjectionRule(SemanticRule[ProjectionClause]):
    """Close the frame onto the projection output and check items and modifiers."""

    __slots__ = ()

    def bindings(self, frame: ScopeFrame, node: ProjectionClause) -> ScopeFrame:
        names = projection_output_names(frame, node)
        # An unknown standalone projection can still acquire node identities from an enclosing call.
        return ScopeFrame(
            names,
            True,
            frame.certified,
            frame.reserved,
            projection_node_declarations(frame, node),
            _projection_unresolved_nodes(frame, node),
        )

    def expression_scope(self, frame: ScopeFrame, node: ProjectionClause) -> ScopeFrame:
        """Let a ``WITH`` filter read the names the ``WITH`` itself introduces."""
        if not isinstance(node, WithClause):
            return frame
        names = _modifier_scope(frame, node)
        if names is None:
            return ScopeFrame(names=None, closed=False, certified=frame.certified)
        return ScopeFrame(names, True, frame.certified, frame.reserved, frame.bindings, frame.unresolved)

    def validate(self, node: ProjectionClause, frame: ScopeFrame) -> None:
        check_references(node.expressions, reference_names(frame), node.keyword)
        validate_projection_modifiers(frame, node)
        self._check_reserved(node, frame)
        if isinstance(node, WithClause) and node.where is not None:
            check_references((node.where.predicate,), _modifier_scope(frame, node), "WHERE")

    def _check_reserved(self, node: ProjectionClause, frame: ScopeFrame) -> None:
        """Reject a ``WITH`` item that aliases an imported name to another value."""
        if not isinstance(node, WithClause):
            return
        for expression in node.expressions:
            if not isinstance(expression, AliasedExpression) or expression.alias_name.value not in frame.reserved:
                continue
            alias = expression.alias_name.value
            inner = expression.expression
            if isinstance(inner, Variable) and inner.symbol.value == alias:
                continue
            raise DslError(
                f"The subquery redeclares imported name {alias!r} in WITH. "
                "Pass the variable through unchanged or alias a different name."
            )


__all__ = [
    "ProjectionRule",
    "projection_node_declarations",
    "projection_output_names",
    "validate_projection_modifiers",
]

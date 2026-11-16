"""
Referenceable names derived from a clause sequence.

Scope is derived from the clauses on demand rather than stored beside them, so a shared
prefix can grow into several branches without one branch changing another.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from cypher_dsl.clauses.base import Clause
from cypher_dsl.clauses.projection import ReturnClause, WithClause
from cypher_dsl.clauses.write import CreateClause, MergeClause
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.functions import Asterisk, RawExpression
from cypher_dsl.expressions.values import AliasedExpression, Variable
from cypher_dsl.patterns.nodes import NodePattern, PatternElement, PatternProperties, _same_node_declaration
from cypher_dsl.patterns.relationships import RelationshipPattern
from cypher_dsl.syntax import AstNode


@dataclass(frozen=True, weakref_slot=True, slots=True)
class _Scope:
    """
    Referenceable names at one point in a statement, in declaration order.

    ``names`` is ``None`` when the names cannot be enumerated, for example after a
    ``WITH`` whose output is trusted raw text. ``closed`` records whether a ``WITH``
    boundary has already applied. Before the first boundary, unbound references remain
    uncertified, so they are not rejected. A closed scope is the post-``WITH`` scope the
    rest of the statement must respect.
    """

    names: tuple[str, ...] | None = None
    closed: bool = False
    # Declaration content is needed only to distinguish compatible write endpoints
    # from conflicting redeclarations. It is not a schema or inferred value type.
    node_declarations: tuple[tuple[str, NodePattern], ...] = ()


class DeclarationRole(Enum):
    """Whether a node pattern occurrence declares a name or refers to one."""

    DECLARE = "DECLARE"
    REFERENCE = "REFERENCE"


@dataclass(frozen=True, weakref_slot=True, slots=True)
class WriteDeclaration:
    """Classification of one node pattern occurrence in a write clause."""

    node: NodePattern
    role: DeclarationRole


def classify_write_declarations(
    scope: _Scope,
    patterns: tuple[PatternElement, ...],
    keyword: str,
) -> tuple[WriteDeclaration, ...]:
    """
    Classify the node patterns of a write clause and reject invalid redeclarations.

    A relationship endpoint in ``CREATE`` or ``MERGE`` may refer to a compatible node an
    earlier clause bound. Declaring a standalone bound node, or an endpoint whose labels
    or properties differ from the bound node, is rejected. Declarations made earlier in
    the same clause count as bound, in child order.
    """
    declarations = dict(scope.node_declarations)
    bound_names = set(scope.names or ()) | declarations.keys()
    classified: list[WriteDeclaration] = []
    for pattern in patterns:
        endpoint_nodes: set[int] = set()
        if isinstance(pattern, RelationshipPattern):
            endpoint_nodes = {id(pattern.start)}
            endpoint_nodes.update(id(hop.right) for hop in pattern.relationships)
        for node in pattern.nodes():
            if node.variable is None:
                continue
            variable = node.variable.value
            if variable in bound_names:
                if id(node) not in endpoint_nodes or isinstance(pattern, NodePattern):
                    raise DslError(f"{keyword} cannot redeclare bound standalone node {variable!r}.")
                previous = declarations.get(variable)
                if previous is None or not _same_node_declaration(previous, node):
                    raise DslError(f"{keyword} has a conflicting declaration for bound endpoint {variable!r}.")
                classified.append(WriteDeclaration(node, DeclarationRole.REFERENCE))
            else:
                bound_names.add(variable)
                declarations[variable] = node
                classified.append(WriteDeclaration(node, DeclarationRole.DECLARE))
        if isinstance(pattern, RelationshipPattern):
            for relationship in pattern.relationships:
                if relationship.variable is None:
                    continue
                variable = relationship.variable.value
                if variable in bound_names:
                    raise DslError(f"{keyword} cannot redeclare bound relationship variable {variable!r}.")
                bound_names.add(variable)
    return tuple(classified)


def _reference_names(scope: _Scope) -> tuple[str, ...] | None:
    """Return the names a reference may use, or ``None`` when checking is not safe."""
    return scope.names if scope.closed else None


def _merge_names(*groups: tuple[str, ...]) -> tuple[str, ...]:
    """Join name groups in first-declaration order without duplicates."""
    ordered: dict[str, None] = {}
    for group in groups:
        for name in group:
            ordered.setdefault(name, None)
    return tuple(ordered)


def _scope_after(clauses: tuple[Clause, ...]) -> _Scope:
    scope = _Scope(())
    for clause in clauses:
        scope = _scope_after_clause(scope, clause)
    return scope


def _scope_after_clause(scope: _Scope, clause: Clause) -> _Scope:
    """
    Apply one clause's effect on the referenceable names.

    A ``MATCH`` contributes the names its patterns bind. A ``WITH`` replaces the names
    with its projection output and closes the scope. An unknown scope stays unknown:
    once a projection has an output this library cannot name, adding bindings cannot
    make the whole scope enumerable again.
    """
    from cypher_dsl.clauses.match import MatchClause
    from cypher_dsl.clauses.unwind import UnwindClause

    if isinstance(clause, (MatchClause, CreateClause, MergeClause)):
        patterns = (clause.pattern,) if isinstance(clause, MergeClause) else clause.patterns
        names = None if scope.names is None else _merge_names(scope.names, _pattern_bindings(patterns))
        declarations = dict(scope.node_declarations)
        for pattern in patterns:
            for node in pattern.nodes():
                if node.variable is not None:
                    declarations.setdefault(node.variable.value, node)
        return _Scope(names, scope.closed, tuple(declarations.items()))
    if isinstance(clause, UnwindClause):
        if scope.names is None:
            return scope
        return _Scope(_merge_names(scope.names, (clause.variable.symbol.value,)), scope.closed, scope.node_declarations)
    if isinstance(clause, WithClause):
        return _Scope(_with_output_names(scope, clause), True, _with_node_declarations(scope, clause))
    if isinstance(clause, ReturnClause):
        return scope
    return scope


def _with_output_names(scope: _Scope, clause: WithClause) -> tuple[str, ...] | None:
    """
    Return the names a ``WITH`` leaves in scope for the clauses after it.

    A wildcard keeps the incoming names. A trusted raw projection may introduce any
    name, so it makes the result unknown rather than certifying an incomplete list.
    """
    names: list[str] = []
    for expression in clause.expressions:
        if isinstance(expression, Asterisk):
            if scope.names is None:
                return None
            names.extend(scope.names)
        elif isinstance(expression, Variable):
            names.append(expression.symbol.value)
        elif isinstance(expression, AliasedExpression):
            names.append(expression.alias_name.value)
        elif isinstance(expression, RawExpression):
            return None
        else:
            return None
    return _merge_names(tuple(names))


def _with_node_declarations(scope: _Scope, clause: WithClause) -> tuple[tuple[str, NodePattern], ...]:
    """
    Carry known node identities through retained variables and aliases only.

    A computed value with the same alias does not retain a node declaration. Trusted
    raw projections remain uncertified, so they do not establish which nodes survived.
    """
    incoming = dict(scope.node_declarations)
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


def _pattern_bindings(patterns: tuple[PatternElement, ...]) -> tuple[str, ...]:
    """Return the names a pattern list binds, in pattern order."""
    names: list[str] = []
    for pattern in patterns:
        for node in pattern.nodes():
            if node.variable is not None:
                names.append(node.variable.value)
        if isinstance(pattern, RelationshipPattern):
            for hop in pattern.relationships:
                if hop.variable is not None:
                    names.append(hop.variable.value)
    return _merge_names(tuple(names))


def _pattern_property_references(patterns: tuple[PatternElement, ...]) -> tuple[Variable, ...]:
    """
    Return the variables used by pattern property values.

    Those values are expressions, not declarations. A later ``MATCH`` pattern binds its
    own variables, but each property value still has to read a name that is available at
    that point in the statement.
    """
    references: list[Variable] = []
    for pattern in patterns:
        for properties in pattern.property_maps():
            if isinstance(properties, PatternProperties):
                for value in properties.children():
                    references.extend(_variables_in(value))
            else:
                references.extend(_variables_in(properties))
    return tuple(references)


def _variables_in(node: AstNode) -> tuple[Variable, ...]:
    found: list[Variable] = []
    if isinstance(node, Variable):
        found.append(node)
    for child in node.children():
        found.extend(_variables_in(child))
    return tuple(found)

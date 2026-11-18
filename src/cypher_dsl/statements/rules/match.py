"""The MATCH rule: pattern bindings, pattern references and declaration facts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cypher_dsl.clauses.match import MatchClause
from cypher_dsl.patterns.nodes import NodePattern, PatternElement, _same_node_declaration
from cypher_dsl.patterns.relationships import RelationshipPattern
from cypher_dsl.statements.frames import (
    DeclarationRole,
    PatternDeclaration,
    ScopeFrame,
    merge_names,
    reference_names,
)
from cypher_dsl.statements.rules.base import (
    SemanticRule,
    check_references,
    reject_reserved_redeclaration,
    reserved_name_conflict,
)
from cypher_dsl.statements.rules.patterns import pattern_bindings, pattern_property_references, pattern_transition

if TYPE_CHECKING:
    from cypher_dsl.statements.rules.base import PatternState


def _classify_match_declarations(
    incoming: ScopeFrame, patterns: tuple[PatternElement, ...]
) -> tuple[PatternDeclaration, ...]:
    """
    Classify each named node occurrence in a pattern list against the scope in front of it.

    A name already bound with the same declaration is a reference: the occurrence
    restates what the scope already holds, and its labels and properties are vacuous
    predicates. A differing declaration filters the bound node, so it stays a
    declaration and renders in full. A name bound without node identity cannot be
    proven vacuous and also stays a declaration. A name first bound inside this
    pattern list declares, and a later occurrence of it in the same list restates that
    first occurrence.

    A name bound before this list whose occurrence declares differently stays a
    declaration, and the incoming binding remains the comparison base for later
    occurrences in the same list, so repeating the differing form filters again while
    restating the incoming form is vacuous.

    Returns:
        One classification per named node occurrence, in pattern order.
    """
    declarations = dict(incoming.bindings)
    classified: list[PatternDeclaration] = []
    for pattern in patterns:
        for node_pattern in pattern.nodes():
            if node_pattern.variable is None:
                continue
            variable = node_pattern.variable.value
            previous = declarations.get(variable)
            if previous is not None and _same_node_declaration(previous, node_pattern):
                classified.append(PatternDeclaration(node_pattern, DeclarationRole.REFERENCE))
                continue
            if previous is None:
                declarations[variable] = node_pattern
            classified.append(PatternDeclaration(node_pattern, DeclarationRole.DECLARE))
    return tuple(classified)


class MatchRule(SemanticRule[MatchClause]):
    """Bind pattern names, check pattern references and classify each pattern occurrence."""

    __slots__ = ()

    def bindings(self, frame: ScopeFrame, node: MatchClause) -> ScopeFrame:
        return pattern_transition(frame, node.patterns)

    def expression_scope(self, frame: ScopeFrame, node: MatchClause) -> ScopeFrame:
        """Let a filter read the names the clause's own patterns bind."""
        return self.bindings(frame, node)

    def validate(self, node: MatchClause, frame: ScopeFrame) -> None:
        if frame.closed and frame.names is not None:
            available = merge_names(frame.names, pattern_bindings(node.patterns))
            check_references(pattern_property_references(node.patterns), available, "MATCH pattern properties")
        self._check_reserved(node, frame)
        if node.where is not None:
            after = self.bindings(frame, node)
            check_references((node.where.predicate,), reference_names(after), "WHERE")

    def pattern_role(
        self, clause: MatchClause, node_pattern: NodePattern, frame: ScopeFrame, state: PatternState
    ) -> DeclarationRole | None:
        """
        Classify one node pattern occurrence against the scope in front of the clause.

        Occurrences the clause's own patterns do not hold, such as a chain inside a
        ``WHERE`` path pattern expression, answer ``None`` so the enclosing
        expression's rule classifies them.
        """
        if node_pattern.variable is None:
            return DeclarationRole.DECLARE
        if state.declarations is None:
            state.declarations = _classify_match_declarations(state.incoming, clause.patterns)
        declarations = state.declarations
        if state.next_declaration < len(declarations):
            declaration = declarations[state.next_declaration]
            if declaration.node is node_pattern:
                state.next_declaration += 1
                return declaration.role
        return None

    def _check_reserved(self, node: MatchClause, frame: ScopeFrame) -> None:
        if not frame.reserved:
            return
        declarations = dict(frame.bindings)
        for pattern in node.patterns:
            for node_pattern in pattern.nodes():
                variable = node_pattern.variable
                if variable is None or variable.value not in frame.reserved:
                    continue
                if reserved_name_conflict(frame, variable.value):
                    reject_reserved_redeclaration(variable.value)
            if not isinstance(pattern, RelationshipPattern):
                continue
            for relationship in pattern.relationships:
                variable = relationship.variable
                if variable is None or variable.value not in frame.reserved:
                    continue
                if variable.value in declarations or reserved_name_conflict(frame, variable.value):
                    reject_reserved_redeclaration(variable.value)

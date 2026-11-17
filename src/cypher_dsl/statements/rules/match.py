"""The MATCH rule: pattern bindings, pattern references and declaration facts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cypher_dsl.clauses.match import MatchClause
from cypher_dsl.patterns.nodes import NodePattern
from cypher_dsl.patterns.relationships import RelationshipPattern
from cypher_dsl.statements.frames import DeclarationRole, ScopeFrame, merge_names, reference_names
from cypher_dsl.statements.rules.base import (
    SemanticRule,
    check_references,
    reject_reserved_redeclaration,
    reserved_name_conflict,
)
from cypher_dsl.statements.rules.patterns import pattern_bindings, pattern_property_references, pattern_transition

if TYPE_CHECKING:
    from cypher_dsl.clauses.base import Clause
    from cypher_dsl.statements.rules.base import AnalysisSink, PatternState  # noqa: F401


class MatchRule(SemanticRule):
    """Bind pattern names, check pattern references and mark every pattern a declaration."""

    __slots__ = ()

    def bindings(self, frame: ScopeFrame, node: MatchClause) -> ScopeFrame:  # type: ignore[override]
        return pattern_transition(frame, node.patterns)

    def validate(self, node: MatchClause, frame: ScopeFrame) -> None:  # type: ignore[override]
        if frame.closed and frame.names is not None:
            available = merge_names(frame.names, pattern_bindings(node.patterns))
            check_references(pattern_property_references(node.patterns), available, "MATCH pattern properties")
        self._check_reserved(node, frame)
        if node.where is not None:
            after = self.bindings(frame, node)
            check_references((node.where.predicate,), reference_names(after), "WHERE")

    def pattern_role(
        self, clause: Clause, node_pattern: NodePattern, frame: ScopeFrame, state: PatternState
    ) -> DeclarationRole | None:
        return DeclarationRole.DECLARE

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
            for hop in pattern.relationships:
                variable = hop.variable
                if variable is None or variable.value not in frame.reserved:
                    continue
                if variable.value in declarations or reserved_name_conflict(frame, variable.value):
                    reject_reserved_redeclaration(variable.value)

"""Occurrence analysis for one finalised AST."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from cypher_dsl.ast import AstNode, OccurrenceFacts, OccurrencePath, _Visitor
from cypher_dsl.clauses.base import Clause
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.values import Parameter
from cypher_dsl.patterns.nodes import NodePattern
from cypher_dsl.statements.composition import Statement, UnionStatement
from cypher_dsl.statements.frames import (
    DeclarationRole,
    NodePatternFacts,
    NoFacts,
    PatternDeclaration,
    ScopeFrame,
    SyntaxRequirement,
)
from cypher_dsl.statements.rules import PatternState, SemanticRules, semantic_rules
from cypher_dsl.statements.rules.base import AnalysisSink
from cypher_dsl.statements.rules.flow import union_columns_check


@dataclass(frozen=True, weakref_slot=True, slots=True)
class Analysis:
    """Read-only analysis products for one render."""

    facts: Mapping[OccurrencePath, OccurrenceFacts]
    requirements: tuple[SyntaxRequirement, ...]
    parameters: tuple[Parameter, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "facts", MappingProxyType(dict(self.facts)))

    def facts_for(self, path: OccurrencePath) -> OccurrenceFacts:
        """Return the stored facts, or immutable empty facts for an ordinary occurrence."""
        return self.facts.get(path, NoFacts())


class _SemanticVisitor(_Visitor):
    """Validate constructs, advance scope frames and derive occurrence products in one walk."""

    __slots__ = (
        "__weakref__",
        "_body_depth_contributions",
        "_body_validation_depth",
        "_child_indices",
        "_clause_states",
        "_clauses",
        "_facts",
        "_frames",
        "_nodes",
        "_parameters",
        "_path",
        "_requirements",
        "_rules",
    )

    def __init__(self) -> None:
        self._rules: SemanticRules = semantic_rules()
        self._body_depth_contributions: list[int] = []
        self._body_validation_depth = 0
        self._frames: list[ScopeFrame] = [ScopeFrame((), certified=True)]
        self._nodes: list[AstNode] = []
        self._clauses: list[Clause] = []
        self._clause_states: list[PatternState] = []
        self._facts: dict[OccurrencePath, OccurrenceFacts] = {}
        self._requirements: list[SyntaxRequirement] = []
        self._parameters: list[Parameter] = []
        self._path: list[OccurrencePath] = []
        self._child_indices: list[int] = []

    def enter(self, node: AstNode) -> None:
        """Assign the occurrence path, seed nested statements and dispatch to rules."""
        if self._path:
            child_index = self._child_indices[-1]
            self._child_indices[-1] += 1
            self._path.append((*self._path[-1], child_index))
        else:
            self._path.append(())
        self._child_indices.append(0)

        if isinstance(node, (Statement, UnionStatement)):
            parent = self._nodes[-1] if self._nodes else None
            contribution = 0
            if parent is None:
                seed = ScopeFrame((), certified=True)
                if isinstance(node, UnionStatement):
                    union_columns_check(node.parts, seed)
            else:
                parent_rule = self._rules.resolve(parent)
                seed = parent_rule.enter_body(self._frames[-1], parent)
                if parent_rule.validates_body:
                    contribution = 1
                if isinstance(node, UnionStatement):
                    parent_rule.check_union(node.parts, seed)
            self._body_depth_contributions.append(contribution)
            self._body_validation_depth += contribution
            self._frames.append(seed)
        rule = self._rules.resolve(node) if isinstance(node, Clause) else self._rules.find(node)
        if rule is not None:
            if not isinstance(node, Clause) or self._body_validation_depth == 0:
                rule.validate(node, self._frames[-1])
            rule.record(node, self._frames[-1], AnalysisSink(self._facts, self._requirements, self._path[-1]))
        if isinstance(node, Clause):
            self._clauses.append(node)
            self._clause_states.append(PatternState(self._frames[-1]))
            self._frames.append(self._rules.resolve(node).expression_scope(self._frames[-1], node))
        self._nodes.append(node)

    def leave(self, node: AstNode) -> None:
        """Record pattern facts, advance the frame and restore traversal state."""
        path = self._path[-1]
        if isinstance(node, NodePattern) and self._clauses:
            clause = self._clauses[-1]
            role = self._rules.resolve(clause).pattern_role(clause, node, self._frames[-1], self._clause_states[-1])
            if role is None:
                role = self._path_pattern_role(node)
            if role is not None:
                self._facts[path] = NodePatternFacts(role)
        if isinstance(node, Parameter):
            self._parameters.append(node)
        if isinstance(node, Clause):
            self._clauses.pop()
            self._clause_states.pop()
            self._frames.pop()
            self._frames[-1] = self._rules.resolve(node).bindings(self._frames[-1], node)
        if isinstance(node, (Statement, UnionStatement)):
            self._frames.pop()
            self._body_validation_depth -= self._body_depth_contributions.pop()
        self._nodes.pop()
        self._child_indices.pop()
        self._path.pop()

    def _path_pattern_role(self, node_pattern: NodePattern) -> DeclarationRole | None:
        """
        Return the declaration role an enclosing path pattern expression assigns.

        A clause whose own rule yields no role, such as the filter of a ``WITH`` or a
        procedure call, still has to render the node patterns inside one of its
        expressions. Those occurrences belong to the expression, so the expression's
        rule supplies their role. A node pattern with no such ancestor keeps the
        clause's answer.
        """
        from cypher_dsl.expressions.path_patterns import PathPatternExpression

        for ancestor in reversed(self._nodes[:-1]):
            if isinstance(ancestor, PathPatternExpression):
                return self._rules.resolve(ancestor).pattern_role(
                    ancestor, node_pattern, self._frames[-1], self._clause_states[-1]
                )
        return None

    def result(self) -> Analysis:
        """Return independent immutable products for the visited AST."""
        return Analysis(dict(self._facts), tuple(self._requirements), tuple(self._parameters))


def analyse(statement: Statement | UnionStatement) -> Analysis:
    """Validate one finalised AST and derive its occurrence products in a single walk."""
    if not isinstance(statement, (Statement, UnionStatement)):
        raise DslError(f"Analysis expects a finalised statement or union, not {type(statement).__name__}.")
    visitor = _SemanticVisitor()
    statement.accept(visitor)
    return visitor.result()


__all__ = [
    "Analysis",
    "DeclarationRole",
    "NoFacts",
    "NodePatternFacts",
    "PatternDeclaration",
    "SyntaxRequirement",
    "analyse",
]

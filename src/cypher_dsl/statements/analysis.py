"""Occurrence analysis for one finalised AST."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from cypher_dsl.clauses.base import Clause
from cypher_dsl.clauses.match import MatchClause
from cypher_dsl.clauses.write import Assignment, CreateClause, MergeClause, RemoveClause
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.properties import SubscriptExpression
from cypher_dsl.expressions.values import Parameter
from cypher_dsl.features import Capability
from cypher_dsl.patterns.nodes import NodePattern
from cypher_dsl.statements.composition import Statement, UnionStatement
from cypher_dsl.statements.scope import (
    DeclarationRole,
    WriteDeclaration,
    _Scope,
    _scope_after_clause,
    classify_write_declarations,
)
from cypher_dsl.syntax import AstNode, OccurrenceFacts, OccurrencePath, _Visitor


@dataclass(frozen=True, weakref_slot=True, slots=True)
class NoFacts(OccurrenceFacts):
    """Facts for an occurrence that needs no additional semantic information."""


@dataclass(frozen=True, weakref_slot=True, slots=True)
class NodePatternFacts(OccurrenceFacts):
    """Declaration role for one node pattern occurrence."""

    role: DeclarationRole


@dataclass(frozen=True, weakref_slot=True, slots=True)
class SyntaxRequirement:
    """A capability required by one AST occurrence."""

    capability: Capability
    path: OccurrencePath


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


@dataclass(weakref_slot=True, slots=True)
class _ClauseFrame:
    """A clause being visited and its cached write declarations."""

    clause: Clause
    declarations: tuple[WriteDeclaration, ...] | None = None
    # Ordered consumption distinguishes roles when one object occupies several pattern positions.
    next_declaration: int = 0


class _AnalysisVisitor(_Visitor):
    """Derive occurrence products while keeping statement scopes and occurrence paths separate."""

    __slots__ = (
        "__weakref__",
        "_child_indices",
        "_clause_stack",
        "_facts",
        "_parameters",
        "_path",
        "_requirements",
        "_scopes",
    )

    def __init__(self) -> None:
        self._facts: dict[OccurrencePath, OccurrenceFacts] = {}
        self._parameters: list[Parameter] = []
        self._requirements: list[SyntaxRequirement] = []
        self._path: list[OccurrencePath] = []
        self._child_indices: list[int] = []
        self._scopes: list[_Scope] = [_Scope(())]
        self._clause_stack: list[_ClauseFrame] = []

    def enter(self, node: AstNode) -> None:
        """Push the occurrence path and any scope or clause state for a node."""
        if self._path:
            child_index = self._child_indices[-1]
            self._child_indices[-1] += 1
            self._path.append((*self._path[-1], child_index))
        else:
            self._path.append(())
        self._child_indices.append(0)

        if isinstance(node, Statement):
            self._scopes.append(_Scope(()))
        if isinstance(node, Clause):
            self._clause_stack.append(_ClauseFrame(node))
        if isinstance(node, Assignment) and isinstance(node.target, SubscriptExpression):
            self._requirements.append(SyntaxRequirement(Capability.DYNAMIC_PROPERTY_WRITES, (*self._path[-1], 0)))
        if isinstance(node, RemoveClause):
            for index, target in enumerate(node.targets):
                if isinstance(target, SubscriptExpression):
                    self._requirements.append(
                        SyntaxRequirement(Capability.DYNAMIC_PROPERTY_WRITES, (*self._path[-1], index))
                    )

    def leave(self, node: AstNode) -> None:
        """Record the current occurrence and restore the surrounding traversal state."""
        path = self._path[-1]
        if isinstance(node, NodePattern):
            self._record_node_pattern(node, path)
        if isinstance(node, Parameter):
            self._parameters.append(node)
        if isinstance(node, Clause):
            clause = self._clause_stack.pop().clause
            self._scopes[-1] = _scope_after_clause(self._scopes[-1], clause)
        if isinstance(node, Statement):
            self._scopes.pop()
        self._child_indices.pop()
        self._path.pop()

    def result(self) -> Analysis:
        """Return independent immutable products for the visited AST."""
        return Analysis(dict(self._facts), tuple(self._requirements), tuple(self._parameters))

    def _record_node_pattern(self, node: NodePattern, path: OccurrencePath) -> None:
        clause = self._clause_stack[-1].clause
        if isinstance(clause, MatchClause):
            self._facts[path] = NodePatternFacts(DeclarationRole.DECLARE)
            return
        if not isinstance(clause, (CreateClause, MergeClause)):
            return
        if node.variable is None:
            self._facts[path] = NodePatternFacts(DeclarationRole.DECLARE)
            return

        frame = self._clause_stack[-1]
        if frame.declarations is None:
            patterns = (clause.pattern,) if isinstance(clause, MergeClause) else clause.patterns
            keyword = "MERGE" if isinstance(clause, MergeClause) else "CREATE"
            frame.declarations = classify_write_declarations(self._scopes[-1], patterns, keyword)
        if frame.next_declaration < len(frame.declarations):
            declaration = frame.declarations[frame.next_declaration]
            if declaration.node is node:
                frame.next_declaration += 1
                self._facts[path] = NodePatternFacts(declaration.role)


def analyse(statement: Statement | UnionStatement) -> Analysis:
    """Derive occurrence facts, requirements and parameter occurrences for one AST."""
    if not isinstance(statement, (Statement, UnionStatement)):
        raise DslError(f"Analysis expects a finalised statement or union, not {type(statement).__name__}.")
    visitor = _AnalysisVisitor()
    statement.accept(visitor)
    return visitor.result()

"""Write rules: declarations, references and dynamic property requirements."""

from __future__ import annotations

from typing import TYPE_CHECKING, Generic, TypeVar

from cypher_dsl.clauses.write import Assignment, CreateClause, DeleteClause, MergeClause, RemoveClause, SetClause
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.properties import SubscriptExpression
from cypher_dsl.features import Capability
from cypher_dsl.patterns.nodes import NodePattern, PatternElement, _same_node_declaration
from cypher_dsl.patterns.relationships import RelationshipPattern
from cypher_dsl.statements.frames import (
    DeclarationRole,
    ScopeFrame,
    WriteDeclaration,
    free_variables_in,
    merge_names,
    reference_names,
)
from cypher_dsl.statements.rules.base import (
    SemanticRule,
    check_references,
    reject_reserved_redeclaration,
    reserved_name_conflict,
)
from cypher_dsl.statements.rules.patterns import pattern_bindings, pattern_transition

if TYPE_CHECKING:
    from cypher_dsl.expressions.values import Variable
    from cypher_dsl.statements.rules.base import AnalysisSink, PatternState


PatternWriteNode = TypeVar("PatternWriteNode", CreateClause, MergeClause)


def classify_write_declarations(
    frame: ScopeFrame,
    patterns: tuple[PatternElement, ...],
    keyword: str,
) -> tuple[WriteDeclaration, ...]:
    """
    Classify the node patterns of a write clause and reject invalid redeclarations.

    A relationship endpoint in ``CREATE`` or ``MERGE`` may refer to a compatible node an earlier clause bound.
    A standalone bound node, or an endpoint whose labels or properties differ from the bound node, is rejected.
    Declarations made earlier in the same clause count as bound, in child order. Compatibility of an unresolved imported
    endpoint is checked when its enclosing bindings are known.
    """
    declarations = dict(frame.bindings)
    bound_names = set(frame.names or ()) | declarations.keys()
    classified: list[WriteDeclaration] = []
    for pattern in patterns:
        endpoint_nodes: set[int] = set()
        if isinstance(pattern, RelationshipPattern):
            endpoint_nodes = {id(pattern.start)}
            endpoint_nodes.update(id(relationship.right) for relationship in pattern.relationships)
        for node_pattern in pattern.nodes():
            if node_pattern.variable is None:
                continue
            variable = node_pattern.variable.value
            if variable in bound_names:
                if id(node_pattern) not in endpoint_nodes or isinstance(pattern, NodePattern):
                    raise DslError(f"{keyword} cannot redeclare bound standalone node {variable!r}.")
                previous = declarations.get(variable)
                if (previous is None and variable not in frame.unresolved) or (
                    previous is not None and not _same_node_declaration(previous, node_pattern)
                ):
                    raise DslError(f"{keyword} has a conflicting declaration for bound endpoint {variable!r}.")
                classified.append(WriteDeclaration(node_pattern, DeclarationRole.REFERENCE))
            else:
                bound_names.add(variable)
                declarations[variable] = node_pattern
                classified.append(WriteDeclaration(node_pattern, DeclarationRole.DECLARE))
        if isinstance(pattern, RelationshipPattern):
            for relationship in pattern.relationships:
                if relationship.variable is None:
                    continue
                variable = relationship.variable.value
                if variable in bound_names:
                    raise DslError(f"{keyword} cannot redeclare bound relationship variable {variable!r}.")
                bound_names.add(variable)
    return tuple(classified)


def write_property_references(
    patterns: tuple[PatternElement, ...], declarations: tuple[WriteDeclaration, ...]
) -> tuple[Variable, ...]:
    """Return variables in declared node and relationship properties, excluding reference-node properties."""
    classified = iter(declarations)
    references: list[Variable] = []
    for pattern in patterns:
        for node in pattern.nodes():
            role = DeclarationRole.DECLARE if node.variable is None else next(classified).role
            if role is DeclarationRole.DECLARE and node.properties is not None:
                references.extend(free_variables_in(node.properties))
        if isinstance(pattern, RelationshipPattern):
            for relationship in pattern.relationships:
                if relationship.properties is not None:
                    references.extend(free_variables_in(relationship.properties))
    return tuple(references)


class _PatternWriteRule(SemanticRule[PatternWriteNode], Generic[PatternWriteNode]):
    """Bind write patterns, classify declarations and check property references."""

    __slots__ = ()

    keyword: str = ""

    def _patterns(self, node: PatternWriteNode) -> tuple[PatternElement, ...]:
        raise NotImplementedError

    def _classify(self, node: PatternWriteNode, frame: ScopeFrame) -> tuple[WriteDeclaration, ...]:
        return classify_write_declarations(frame, self._patterns(node), self.keyword)

    def validate(self, node: PatternWriteNode, frame: ScopeFrame) -> None:
        self._check_reserved(node, frame)
        declarations = self._classify(node, frame)
        if frame.closed and frame.names is not None:
            available = merge_names(frame.names, pattern_bindings(self._patterns(node)))
            check_references(
                write_property_references(self._patterns(node), declarations),
                available,
                f"{self.keyword} pattern properties",
            )
            self._check_actions(node, available)

    def _check_actions(self, node: PatternWriteNode, available: tuple[str, ...] | None) -> None:
        """Check attached MERGE actions. CREATE has none."""

    def pattern_role(
        self, clause: PatternWriteNode, node_pattern: NodePattern, frame: ScopeFrame, state: PatternState
    ) -> DeclarationRole | None:
        if node_pattern.variable is None:
            return DeclarationRole.DECLARE
        if state.declarations is None:
            state.declarations = self._classify(clause, frame)
        if state.next_declaration < len(state.declarations):
            declaration = state.declarations[state.next_declaration]
            if declaration.node is node_pattern:
                state.next_declaration += 1
                return declaration.role
        return None

    def _check_reserved(self, node: PatternWriteNode, frame: ScopeFrame) -> None:
        if not frame.reserved:
            return
        declarations = dict(frame.bindings)
        for pattern in self._patterns(node):
            for node_pattern in pattern.nodes():
                variable = node_pattern.variable
                if variable is None or variable.value not in frame.reserved:
                    continue
                name = variable.value
                previous = declarations.get(name)
                if (
                    reserved_name_conflict(frame, name)
                    or isinstance(pattern, NodePattern)
                    or (previous is not None and not _same_node_declaration(previous, node_pattern))
                ):
                    reject_reserved_redeclaration(name)
            if isinstance(pattern, RelationshipPattern):
                for relationship in pattern.relationships:
                    if relationship.variable is not None and relationship.variable.value in frame.reserved:
                        reject_reserved_redeclaration(relationship.variable.value)


class CreateRule(_PatternWriteRule[CreateClause]):
    """Bind and validate CREATE patterns."""

    __slots__ = ()

    keyword = "CREATE"

    def _patterns(self, node: CreateClause) -> tuple[PatternElement, ...]:
        return node.patterns

    def bindings(self, frame: ScopeFrame, node: CreateClause) -> ScopeFrame:
        return pattern_transition(frame, node.patterns)


class MergeRule(_PatternWriteRule[MergeClause]):
    """Bind and validate MERGE patterns and their action references."""

    __slots__ = ()

    keyword = "MERGE"

    def _patterns(self, node: MergeClause) -> tuple[PatternElement, ...]:
        return (node.pattern,)

    def bindings(self, frame: ScopeFrame, node: MergeClause) -> ScopeFrame:
        return pattern_transition(frame, (node.pattern,))

    def _check_actions(self, node: MergeClause, available: tuple[str, ...] | None) -> None:
        for action in node.actions:
            check_references(action.updates, available, action.keyword)

    def record(self, node: MergeClause, frame: ScopeFrame, sink: AnalysisSink) -> None:
        for action_index, action in enumerate(node.actions, 1):
            for index, update in enumerate(action.updates):
                if isinstance(update.target, SubscriptExpression):
                    sink.requirement(Capability.DYNAMIC_PROPERTY_WRITES, (*sink.path, action_index, index, 0))


class SetRule(SemanticRule[SetClause]):
    """Check SET references and record dynamic property writes."""

    __slots__ = ()

    def validate(self, node: SetClause, frame: ScopeFrame) -> None:
        check_references(node.updates, reference_names(frame), "SET")

    def record(self, node: SetClause, frame: ScopeFrame, sink: AnalysisSink) -> None:
        for index, update in enumerate(node.updates):
            if isinstance(update, Assignment) and isinstance(update.target, SubscriptExpression):
                sink.requirement(Capability.DYNAMIC_PROPERTY_WRITES, (*sink.path, index, 0))


class RemoveRule(SemanticRule[RemoveClause]):
    """Check REMOVE references and record dynamic property writes."""

    __slots__ = ()

    def validate(self, node: RemoveClause, frame: ScopeFrame) -> None:
        check_references(node.targets, reference_names(frame), "REMOVE")

    def record(self, node: RemoveClause, frame: ScopeFrame, sink: AnalysisSink) -> None:
        for index, target in enumerate(node.targets):
            if isinstance(target, SubscriptExpression):
                sink.requirement(Capability.DYNAMIC_PROPERTY_WRITES, (*sink.path, index))


class DeleteRule(SemanticRule[DeleteClause]):
    """Check DELETE references without changing the frame."""

    __slots__ = ()

    def validate(self, node: DeleteClause, frame: ScopeFrame) -> None:
        check_references(node.targets, reference_names(frame), "DELETE")


__all__ = [
    "CreateRule",
    "DeleteRule",
    "MergeRule",
    "RemoveRule",
    "SetRule",
    "classify_write_declarations",
    "write_property_references",
]

"""The semantic rule contract, the registry and the shared walk helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from cypher_dsl.ast import AstNode, OccurrenceFacts, OccurrencePath
from cypher_dsl.errors import DslError, UnsupportedFeatureError
from cypher_dsl.features import Capability
from cypher_dsl.patterns.nodes import NodePattern
from cypher_dsl.registry import TypeRegistry
from cypher_dsl.statements.frames import (
    DeclarationRole,
    PatternDeclaration,
    ScopeFrame,
    SyntaxRequirement,
    free_variables_in,
)

if TYPE_CHECKING:
    from cypher_dsl.clauses.base import Clause
    from cypher_dsl.statements.composition import Statement


TNode = TypeVar("TNode", bound=AstNode)


class SemanticRule(Generic[TNode]):
    """
    Behaviour of one construct family inside the semantic walk.

    A rule derives the frame after its construct, checks the construct against the
    frame in front of it, records analysis products, and seeds the frame of a
    statement nested under it. ``expression_scope`` names the frame expressions inside
    the construct read against, and ``check_union`` checks a union nested under the
    construct. The defaults keep the frame, accept the construct, record nothing, seed
    an uncertified empty frame, leave the expression scope in front of the construct
    and compare union columns, so a rule states only what its construct changes.

    The type parameter is the construct the rule handles, so each rule's narrowed hook
    signatures match its declaration.

    Attributes:
        validates_body: Whether ``validate`` already validates the bodies nested under this construct, so analysis must
            not validate their clauses again. Non-clause rules still run during analysis.
    """

    __slots__ = ()

    validates_body: bool = False

    def bindings(self, frame: ScopeFrame, node: TNode) -> ScopeFrame:
        """Return the frame after this construct."""
        return frame

    def validate(self, node: TNode, frame: ScopeFrame) -> None:
        """Check this construct against the frame in front of it."""

    def record(self, node: TNode, frame: ScopeFrame, sink: AnalysisSink) -> None:
        """Record analysis products for this occurrence."""

    def enter_body(self, frame: ScopeFrame, node: TNode) -> ScopeFrame:
        """Return the seed frame for a statement nested under this construct."""
        return ScopeFrame()

    def expression_scope(self, frame: ScopeFrame, node: TNode) -> ScopeFrame:
        """
        Return the frame expressions inside this construct read against.

        The default is the frame in front of the construct. A clause whose expressions
        may read names it introduces itself, such as a ``MATCH`` pattern, returns the
        frame after those names.
        """
        return frame

    def check_union(self, parts: tuple[Statement, ...], seed: ScopeFrame) -> None:
        """
        Check a nested union's branches against the context that holds it.

        The default is the column comparison. A construct that discards the union's
        output overrides it with its own branch rule.
        """
        from cypher_dsl.statements.rules.flow import union_columns_check

        union_columns_check(parts, seed)

    def pattern_role(
        self, clause: TNode, node_pattern: NodePattern, frame: ScopeFrame, state: PatternState
    ) -> DeclarationRole | None:
        """Return the declaration role of one node pattern occurrence, or ``None``."""
        return None


class PatternState:
    """Cached pattern classification and the incoming frame for one clause occurrence."""

    __slots__ = ("declarations", "incoming", "next_declaration")

    def __init__(self, incoming: ScopeFrame) -> None:
        self.incoming = incoming
        self.declarations: tuple[PatternDeclaration, ...] | None = None
        self.next_declaration: int = 0


class SemanticRules:
    """Immutable mapping from AST classes to the semantic rules selected for them."""

    __slots__ = ("_rules",)

    def __init__(self, rules: Mapping[type[AstNode], SemanticRule[Any]]) -> None:
        self._rules = TypeRegistry(rules)

    def resolve(self, node: AstNode) -> SemanticRule[Any]:
        """Return the exact rule or the nearest registered class in the node's MRO."""
        rule = self.find(node)
        if rule is None:
            raise UnsupportedFeatureError(f"No semantic rule for {type(node).__name__}.")
        return rule

    def find(self, node: AstNode) -> SemanticRule[Any] | None:
        """Return the nearest registered rule in the node's MRO, or ``None``."""
        return self._rules.find(node)


_RULES: SemanticRules | None = None


class AnalysisSink:
    """Accumulator for the products one rule records at one occurrence."""

    __slots__ = ("_facts", "_path", "_requirements")

    def __init__(
        self,
        facts: dict[OccurrencePath, OccurrenceFacts],
        requirements: list[SyntaxRequirement],
        path: OccurrencePath,
    ) -> None:
        self._facts = facts
        self._requirements = requirements
        self._path = path

    @property
    def path(self) -> OccurrencePath:
        """Return the current occurrence path."""
        return self._path

    def requirement(self, capability: Capability, path: OccurrencePath | None = None) -> None:
        """Record a capability requirement for the current or a named occurrence."""
        self._requirements.append(SyntaxRequirement(capability, self._path if path is None else path))


def semantic_rules() -> SemanticRules:
    """Return the assembled registry, importing the rule modules once."""
    global _RULES
    if _RULES is None:
        from cypher_dsl.statements.rules import shared_rules

        _RULES = SemanticRules(shared_rules())
    return _RULES


def frame_after(clauses: tuple[Clause, ...], initial: ScopeFrame | None = None) -> ScopeFrame:
    """Return the frame after a clause sequence."""
    rules = semantic_rules()
    frame = ScopeFrame() if initial is None else initial
    for clause in clauses:
        frame = rules.resolve(clause).bindings(frame, clause)
    return frame


def validate_clause(frame: ScopeFrame, clause: Clause) -> None:
    """Check one clause and its nested body against the frame in front of it."""
    semantic_rules().resolve(clause).validate(clause, frame)


def walk_clauses(clauses: tuple[Clause, ...], initial: ScopeFrame | None = None) -> None:
    """Check every clause of a statement against the frame in front of it."""
    rules = semantic_rules()
    frame = ScopeFrame() if initial is None else initial
    for clause in clauses:
        rule = rules.resolve(clause)
        rule.validate(clause, frame)
        frame = rule.bindings(frame, clause)


def check_references(expressions: Sequence[AstNode], names: tuple[str, ...] | None, construct: str) -> None:
    """
    Reject a reference to a name the available frame does not contain.

    This is structural checking, not full semantic analysis. It runs only when the
    caller has a name list to check against, and only for variables the expression
    tree actually contains.
    """
    if names is None:
        return
    for expression in expressions:
        for variable in free_variables_in(expression):
            if variable.symbol.value not in names:
                raise DslError(
                    f"{construct} refers to {variable.symbol.value!r}, which is not in scope. "
                    "A WITH clause keeps only the names it projects. "
                    "Project the name or alias the value before referring to it."
                )


def reserved_name_conflict(frame: ScopeFrame, name: str) -> bool:
    """
    Return whether a reserved name is provably not a visible import reference.

    A reserved name the frame still carries may be referenced; one the frame no longer
    carries was discarded by a projection, so rebinding it hides the import. An
    uncertified frame cannot prove either and tolerates the reference.
    """
    return name in frame.reserved and frame.names is not None and name not in frame.names


def reject_reserved_redeclaration(name: str) -> None:
    """
    Raise the shared rejection for a construct that rebinds an imported name.

    Constructs whose advice differs keep their own raise. ``WITH`` does, because the
    remedy there is to pass the variable through unchanged rather than to rename.
    """
    raise DslError(f"The subquery redeclares imported name {name!r}. Bind a different name inside the subquery.")

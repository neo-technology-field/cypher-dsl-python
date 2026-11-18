"""The subquery rules: CALL import scope and the subquery expression body."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cypher_dsl.clauses.call import SubqueryCallClause
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.subqueries import SubqueryExpression
from cypher_dsl.features import Capability
from cypher_dsl.patterns.nodes import _same_node_declaration
from cypher_dsl.statements.frames import ScopeFrame, is_unresolved_node, merge_names
from cypher_dsl.statements.rules.base import (
    SemanticRule,
    frame_after,
    reject_reserved_redeclaration,
    walk_clauses,
)
from cypher_dsl.statements.rules.flow import union_columns_check
from cypher_dsl.statements.rules.projection import (
    _projection_unresolved_nodes,
    projection_node_declarations,
    projection_output_names,
)

if TYPE_CHECKING:
    from cypher_dsl.statements.composition import Statement, UnionStatement
    from cypher_dsl.statements.rules.base import AnalysisSink


class CallRule(SemanticRule[SubqueryCallClause]):
    """Seed a called body with its imports and check the call against its frame."""

    __slots__ = ()

    validates_body = True

    def enter_body(self, frame: ScopeFrame, node: SubqueryCallClause) -> ScopeFrame:
        if node.import_all:
            names = frame.names if frame.closed or frame.certified else None
        else:
            names = tuple(variable.symbol.value for variable in node.imports)
        bindings = tuple(item for item in frame.bindings if names is None or item[0] in names)
        unresolved = frozenset(name for name in (names or ()) if is_unresolved_node(frame, name))
        return ScopeFrame(
            names,
            True,
            frame.certified or (not node.import_all and not node.imports),
            frozenset(names or ()),
            bindings,
            unresolved,
        )

    def validate(self, node: SubqueryCallClause, frame: ScopeFrame) -> None:
        if not node.import_all and frame.names is not None and (frame.closed or frame.certified):
            for variable in node.imports:
                if variable.symbol.value not in frame.names:
                    raise DslError(
                        f"CALL imports {variable.symbol.value!r}, which is not in scope. "
                        "Import a name the preceding clauses bind."
                    )
        seed = self.enter_body(frame, node)
        from cypher_dsl.statements.composition import UnionStatement, _branches

        branches = _branches(node.subquery)
        for branch in branches:
            walk_clauses(branch.clauses, seed)
        if isinstance(node.subquery, UnionStatement):
            union_columns_check(node.subquery.parts, seed)
        output = output_scope(node.subquery, seed)
        if frame.reserved:
            for name in output.names or ():
                if name in frame.reserved:
                    reject_reserved_redeclaration(name)
        if frame.names is not None and output.names is not None:
            for name in output.names:
                if name in frame.names:
                    raise DslError(
                        f"The subquery returns {name!r}, which the outer query already holds. "
                        "Rename the returned value so the outer scope keeps one binding."
                    )

    def bindings(self, frame: ScopeFrame, node: SubqueryCallClause) -> ScopeFrame:
        output = output_scope(node.subquery, self.enter_body(frame, node))
        names = None if frame.names is None or output.names is None else merge_names(frame.names, output.names)
        bindings = dict(frame.bindings)
        bindings.update(output.bindings)
        return ScopeFrame(
            names,
            frame.closed,
            frame.certified,
            frame.reserved,
            tuple(bindings.items()),
            frame.unresolved | output.unresolved,
        )

    def record(self, node: SubqueryCallClause, frame: ScopeFrame, sink: AnalysisSink) -> None:
        sink.requirement(Capability.SCOPE_CLAUSES)
        if node.optional:
            sink.requirement(Capability.OPTIONAL_CALL)
        if node.in_transactions:
            sink.requirement(Capability.IN_TRANSACTIONS)


def output_scope(subquery: Statement | UnionStatement, initial: ScopeFrame) -> ScopeFrame:
    """Return the final projection's names and node identities, or an empty frame for a unit body."""
    from cypher_dsl.clauses.projection import ReturnClause
    from cypher_dsl.statements.composition import UnionStatement

    statements = subquery.parts if isinstance(subquery, UnionStatement) else (subquery,)
    outputs: list[ScopeFrame] = []
    for statement in statements:
        final = statement.clauses[-1]
        if isinstance(final, ReturnClause):
            inner = frame_after(statement.clauses[:-1], initial)
            outputs.append(
                ScopeFrame(
                    projection_output_names(inner, final),
                    True,
                    True,
                    initial.reserved,
                    projection_node_declarations(inner, final),
                    _projection_unresolved_nodes(inner, final),
                )
            )
        else:
            outputs.append(ScopeFrame((), True, True, initial.reserved))
    names = (
        None
        if any(output.names is None for output in outputs)
        else merge_names(*(output.names or () for output in outputs))
    )
    bindings = dict(outputs[0].bindings)
    for output in outputs[1:]:
        branch = dict(output.bindings)
        bindings = {
            binding_name: declaration
            for binding_name, declaration in bindings.items()
            if binding_name in branch and _same_node_declaration(declaration, branch[binding_name])
        }
    unresolved = frozenset(name for output in outputs for name in output.unresolved)
    return ScopeFrame(names, True, True, initial.reserved, tuple(bindings.items()), unresolved)


class SubqueryExpressionRule(SemanticRule[SubqueryExpression]):
    """Seed a subquery expression body from the expression scope and walk it as its own query."""

    __slots__ = ()

    validates_body = True

    def enter_body(self, frame: ScopeFrame, node: SubqueryExpression) -> ScopeFrame:
        """
        Return the frame the body starts from.

        The body reads every enclosing name without imports, so the seed keeps the names,
        the node identities and the certification of the frame in front of the
        expression, and reserves nothing. Reserving the outer names would reject a body
        pattern that re-declares one, which is the correlated query Cypher accepts. The
        cost is that a body ``WITH`` binding an enclosing name to a new value, the
        shadowing Cypher rejects, is not detected here.
        """
        return ScopeFrame(
            frame.names,
            True,
            frame.certified,
            frozenset(),
            frame.bindings,
            frame.unresolved,
        )

    def validate(self, node: SubqueryExpression, frame: ScopeFrame) -> None:
        """Walk each body branch from the seed, the way a called body is walked."""
        seed = self.enter_body(frame, node)
        from cypher_dsl.statements.composition import _branches

        branches = _branches(node.subquery)
        for branch in branches:
            walk_clauses(branch.clauses, seed)

    def check_union(self, parts: tuple[Statement, ...], seed: ScopeFrame) -> None:
        """Require RETURN in every branch or in none, because the output is discarded."""
        from cypher_dsl.clauses.projection import ReturnClause

        returning = [isinstance(part.clauses[-1], ReturnClause) for part in parts]
        if any(returning) and not all(returning):
            raise DslError(
                "The subquery expression body's UNION branches mix a final RETURN with branches that end "
                "without one. All branches must end in RETURN, or none must."
            )


__all__ = ["CallRule", "SubqueryExpressionRule", "output_scope"]

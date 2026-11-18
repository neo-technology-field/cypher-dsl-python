"""The CALL rules: subquery import scope and procedure yield bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cypher_dsl.clauses.call import ProcedureCallClause, SubqueryCallClause
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.values import AliasedExpression
from cypher_dsl.features import Capability
from cypher_dsl.patterns.nodes import _same_node_declaration
from cypher_dsl.statements.frames import ScopeFrame, is_unresolved_node, merge_names, reference_names
from cypher_dsl.statements.rules.base import (
    SemanticRule,
    check_references,
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


class CallRule(SemanticRule):
    """Seed a called body with its imports and check the call against its frame."""

    __slots__ = ()

    validates_body = True

    def enter_body(self, frame: ScopeFrame, node: SubqueryCallClause) -> ScopeFrame:  # type: ignore[override]
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

    def validate(self, node: SubqueryCallClause, frame: ScopeFrame) -> None:  # type: ignore[override]
        if not node.import_all and frame.names is not None and (frame.closed or frame.certified):
            for variable in node.imports:
                if variable.symbol.value not in frame.names:
                    raise DslError(
                        f"CALL imports {variable.symbol.value!r}, which is not in scope. "
                        "Import a name the preceding clauses bind."
                    )
        seed = self.enter_body(frame, node)
        from cypher_dsl.statements.composition import UnionStatement

        branches = node.subquery.parts if isinstance(node.subquery, UnionStatement) else (node.subquery,)
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

    def bindings(self, frame: ScopeFrame, node: SubqueryCallClause) -> ScopeFrame:  # type: ignore[override]
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

    def record(self, node: SubqueryCallClause, frame: ScopeFrame, sink: AnalysisSink) -> None:  # type: ignore[override]
        sink.requirement(Capability.SCOPE_CLAUSES)
        if node.optional:
            sink.requirement(Capability.OPTIONAL_CALL)
        if node.in_transactions:
            sink.requirement(Capability.IN_TRANSACTIONS)


class ProcedureCallRule(SemanticRule):
    """Bind the names a procedure call yields and check the call against its frame."""

    __slots__ = ()

    def bindings(self, frame: ScopeFrame, node: ProcedureCallClause) -> ScopeFrame:  # type: ignore[override]
        if frame.names is None or not node.yields:
            return frame
        return ScopeFrame(
            merge_names(frame.names, _yielded_bindings(node)),
            frame.closed,
            frame.certified,
            frame.reserved,
            frame.bindings,
            frame.unresolved,
        )

    def validate(self, node: ProcedureCallClause, frame: ScopeFrame) -> None:  # type: ignore[override]
        check_references(node.arguments, reference_names(frame), "CALL")
        bindings = _yielded_bindings(node)
        for binding in bindings:
            if binding in frame.reserved:
                reject_reserved_redeclaration(binding)
            if frame.names is not None and binding in frame.names:
                raise DslError(
                    f"CALL YIELD binds {binding!r}, which the outer query already holds. "
                    "Rename the yielded item so the outer scope keeps one binding."
                )
        if node.predicate is None:
            return
        names = reference_names(frame)
        check_references((node.predicate,), None if names is None else merge_names(names, bindings), "CALL")

    def record(self, node: ProcedureCallClause, frame: ScopeFrame, sink: AnalysisSink) -> None:  # type: ignore[override]
        if node.optional:
            sink.requirement(Capability.OPTIONAL_CALL)


def _yielded_bindings(node: ProcedureCallClause) -> tuple[str, ...]:
    """Return the name each yield item binds, the alias when one is present."""
    return tuple(
        item.alias_name.value if isinstance(item, AliasedExpression) else item.symbol.value for item in node.yields
    )


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


__all__ = ["CallRule", "ProcedureCallRule", "output_scope"]

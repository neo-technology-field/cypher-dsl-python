"""The procedure call rule: yield bindings and the filter that reads them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cypher_dsl.clauses.call import ProcedureCallClause
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.values import AliasedExpression
from cypher_dsl.features import Capability
from cypher_dsl.statements.frames import ScopeFrame, merge_names, reference_names
from cypher_dsl.statements.rules.base import SemanticRule, check_references, reject_reserved_redeclaration

if TYPE_CHECKING:
    from cypher_dsl.statements.rules.base import AnalysisSink


class ProcedureCallRule(SemanticRule[ProcedureCallClause]):
    """Bind the names a procedure call yields and check the call against its frame."""

    __slots__ = ()

    def bindings(self, frame: ScopeFrame, node: ProcedureCallClause) -> ScopeFrame:
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

    def expression_scope(self, frame: ScopeFrame, node: ProcedureCallClause) -> ScopeFrame:
        """Let a call filter read the names the call yields."""
        return self.bindings(frame, node)

    def validate(self, node: ProcedureCallClause, frame: ScopeFrame) -> None:
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

    def record(self, node: ProcedureCallClause, frame: ScopeFrame, sink: AnalysisSink) -> None:
        if node.optional:
            sink.requirement(Capability.OPTIONAL_CALL)


def _yielded_bindings(node: ProcedureCallClause) -> tuple[str, ...]:
    """Return the name each yield item binds, the alias when one is present."""
    return tuple(
        item.alias_name.value if isinstance(item, AliasedExpression) else item.symbol.value for item in node.yields
    )


__all__ = ["ProcedureCallRule"]

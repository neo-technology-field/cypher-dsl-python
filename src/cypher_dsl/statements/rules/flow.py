"""The UNWIND rule and union branch column compatibility."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cypher_dsl.clauses.projection import ReturnClause
from cypher_dsl.clauses.unwind import UnwindClause
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.functions import Asterisk, RawExpression
from cypher_dsl.expressions.values import AliasedExpression, Variable
from cypher_dsl.statements.frames import ScopeFrame, merge_names, reference_names
from cypher_dsl.statements.rules.base import SemanticRule, check_references, frame_after, reject_reserved_redeclaration

if TYPE_CHECKING:
    from cypher_dsl.ast import AstNode
    from cypher_dsl.statements.composition import Statement


class UnwindRule(SemanticRule):
    """Bind one variable per element and check the source references."""

    __slots__ = ()

    def bindings(self, frame: ScopeFrame, node: UnwindClause) -> ScopeFrame:  # type: ignore[override]
        if frame.names is None:
            return frame
        return ScopeFrame(
            merge_names(frame.names, (node.variable.symbol.value,)),
            frame.closed,
            frame.certified,
            frame.reserved,
            frame.bindings,
            frame.unresolved,
        )

    def validate(self, node: UnwindClause, frame: ScopeFrame) -> None:  # type: ignore[override]
        check_references((node.values,), reference_names(frame), "UNWIND")
        if node.variable.symbol.value in frame.reserved:
            reject_reserved_redeclaration(node.variable.symbol.value)


class UnionRule(SemanticRule):
    """Start every union branch from the frame in front of the union."""

    __slots__ = ()

    def enter_body(self, frame: ScopeFrame, node: AstNode) -> ScopeFrame:
        return frame


def union_columns_check(parts: tuple[Statement, ...], initial: ScopeFrame) -> None:
    """Reject union branches whose known result columns disagree in width or name."""
    width: int | None = None
    known_names: list[str | None] = []
    for part in parts:
        columns = _branch_columns(part, initial)
        if columns is None:
            continue
        if width is None:
            width = len(columns)
            known_names.extend([None] * width)
        elif len(columns) != width:
            raise DslError(
                f"UNION branches project {width} and {len(columns)} columns. Branches must project the same width."
            )
        for index, column in enumerate(columns):
            if column is None:
                continue
            known = known_names[index]
            if known is None:
                known_names[index] = column
            elif known != column:
                raise DslError(f"UNION projection names are incompatible: {known!r} and {column!r}.")


def _branch_columns(statement: Statement, initial: ScopeFrame) -> tuple[str | None, ...] | None:
    """
    Return the result columns of a union branch, or ``None`` when the width is unknown.

    A wildcard keeps a known width by expanding the frame in front of ``RETURN``. A
    single wildcard column has only one possible name, so that name is preserved. A
    multi-column wildcard keeps its positions uncertain, because this library does not
    track the server's column order for ``*``. Trusted raw text may stand for more than
    one column, so it makes the width unknown. A wildcard in an open standalone branch has
    unknown width until the frame that surrounds it is known.
    """
    if not statement.clauses:
        raise DslError("UNION requires each part to end with a RETURN clause.")
    owner = statement.clauses[-1]
    if not isinstance(owner, ReturnClause):
        raise DslError("UNION requires each part to end with a RETURN clause.")
    frame = frame_after(statement.clauses[:-1], initial)
    columns: list[str | None] = []
    for expression in owner.expressions:
        if isinstance(expression, Asterisk):
            if (
                frame.names is None
                or (not frame.closed and not frame.certified)
                or (not statement.clauses[:-1] and not (frame.names or ()))
            ):
                return None
            if len(frame.names) == 1:
                columns.append(frame.names[0])
            else:
                columns.extend([None] * len(frame.names))
        elif isinstance(expression, AliasedExpression):
            columns.append(expression.alias_name.value)
        elif isinstance(expression, RawExpression):
            return None
        elif isinstance(expression, Variable):
            columns.append(expression.symbol.value)
        else:
            columns.append(None)
    return tuple(columns)

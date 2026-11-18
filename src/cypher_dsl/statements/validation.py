"""
Checks that reject an invalid clause sequence before a renderer sees it.

A clause is checked against the scope in front of it, and a projection is rechecked when
a modifier replaces it. The checks cover clause order, known references and binding
declarations, not server-side semantics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cypher_dsl.clauses.base import Clause
from cypher_dsl.clauses.projection import ReturnClause, WithClause
from cypher_dsl.clauses.write import CreateClause, DeleteClause, MergeClause, RemoveClause, SetClause
from cypher_dsl.errors import DslError, InvalidClauseOrderError
from cypher_dsl.statements.rules import walk_clauses

if TYPE_CHECKING:
    from cypher_dsl.statements.composition import Statement, UnionStatement

# Clauses that change the graph. They can end a statement without a RETURN, and once one
# appears in the current query part a further MATCH needs a WITH boundary.
_UPDATE_CLAUSES = (CreateClause, MergeClause, SetClause, RemoveClause, DeleteClause)


def _current_part_has_update(clauses: tuple[Clause, ...]) -> bool:
    """
    Return whether the current query part already contains an updating clause.

    A ``WITH`` starts a new part, so a read after it is allowed. Reading again in the
    same part after a write is not part of the grammar.
    """
    for clause in reversed(clauses):
        if isinstance(clause, WithClause):
            return False
        if isinstance(clause, _UPDATE_CLAUSES):
            return True
    return False


def require_appendable(clauses: tuple[Clause, ...], keyword: str) -> None:
    """Reject a clause that would follow the statement's final ``RETURN``."""
    if clauses and isinstance(clauses[-1], ReturnClause):
        raise InvalidClauseOrderError(f"{keyword} must precede RETURN in a statement.")


_READ_HINTS = {
    "CALL": "Add with_() before the CALL.",
    "MATCH": "Add with_() before reading again.",
    "UNWIND": "Add with_() before reading again.",
}


def require_read_position(clauses: tuple[Clause, ...], keyword: str) -> None:
    """
    Reject a reading clause that follows ``RETURN`` or an unseparated update.

    Reading again after a write in the same query part is not part of the grammar; a
    ``WITH`` boundary starts a new part and makes the read legal.
    """
    require_appendable(clauses, keyword)
    if _current_part_has_update(clauses):
        raise InvalidClauseOrderError(
            f"{keyword} after an updating clause needs a WITH boundary. {_READ_HINTS[keyword]}"
        )


def require_update_position(clauses: tuple[Clause, ...], keyword: str) -> None:
    """
    Reject an update that has nothing to modify or that follows ``RETURN``.

    A ``SET``, ``REMOVE`` or deletion cannot introduce the element it writes. Those
    clauses therefore need an earlier clause, while ``CREATE`` and ``MERGE`` can start a
    statement.
    """
    require_appendable(clauses, keyword)
    if not clauses:
        raise InvalidClauseOrderError(
            f"{keyword} needs a preceding clause that binds its target. Start with match(), create() or merge()."
        )


def _subquery_returns(subquery: Statement | UnionStatement) -> bool:
    """Return whether a subquery has a final ``RETURN`` projection."""
    from cypher_dsl.clauses.projection import ReturnClause
    from cypher_dsl.statements.composition import UnionStatement

    return isinstance(subquery, UnionStatement) or isinstance(subquery.clauses[-1], ReturnClause)


def _validate_statement_clauses(clauses: tuple[Clause, ...]) -> None:
    from cypher_dsl.clauses.call import ProcedureCallClause, SubqueryCallClause
    from cypher_dsl.clauses.match import MatchClause
    from cypher_dsl.clauses.unwind import UnwindClause

    if not clauses:
        raise DslError("A statement needs at least one clause before it can be rendered.")
    if any(isinstance(clause, ReturnClause) for clause in clauses[:-1]):
        raise InvalidClauseOrderError("RETURN must be the final clause and can appear only once in a statement.")
    for index, clause in enumerate(clauses):
        prefix = clauses[:index]
        if isinstance(clause, SetClause):
            require_update_position(prefix, "SET")
        elif isinstance(clause, RemoveClause):
            require_update_position(prefix, "REMOVE")
        elif isinstance(clause, DeleteClause):
            require_update_position(prefix, "DETACH DELETE" if clause.detach else "DELETE")
        elif isinstance(clause, MatchClause):
            require_read_position(prefix, "MATCH")
        elif isinstance(clause, UnwindClause):
            require_read_position(prefix, "UNWIND")
        elif isinstance(clause, (SubqueryCallClause, ProcedureCallClause)):
            require_read_position(prefix, "CALL")
    final = clauses[-1]
    if isinstance(final, SubqueryCallClause):
        if _subquery_returns(final.subquery):
            raise DslError(
                "A returning subquery cannot end a statement. Add a RETURN clause or another clause after the CALL."
            )
    elif isinstance(final, ProcedureCallClause):
        if final.yields:
            raise DslError(
                "A CALL with YIELD items cannot end a statement. The yielded names must feed a following clause, "
                "so add a RETURN or another clause."
            )
    elif not isinstance(final, (ReturnClause, *_UPDATE_CLAUSES)):
        raise DslError(
            "A statement must end with a RETURN clause or a write clause. A read that stops at MATCH is incomplete."
        )
    walk_clauses(clauses)

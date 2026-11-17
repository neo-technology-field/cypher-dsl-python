"""
The builder path and direct statement construction apply the same order policy.

Every invalid sequence is rejected twice: once when the builder appends the offending
clause, and once when the same clause sequence is finalised directly. The messages are
the policy, so both paths must raise with identical text.
"""

from __future__ import annotations

import re

import pytest

from cypher_dsl import create, match, node
from cypher_dsl.clauses.match import MatchClause
from cypher_dsl.clauses.projection import ReturnClause
from cypher_dsl.clauses.write import CreateClause, SetClause
from cypher_dsl.errors import InvalidClauseOrderError
from cypher_dsl.expressions.values import SymbolicName, Variable
from cypher_dsl.statements.composition import Statement


def _variable(name: str) -> Variable:
    return Variable(SymbolicName(name))


def test_read_after_write_rejected_identically() -> None:
    message = "MATCH after an updating clause needs a WITH boundary. Add with_() before reading again."
    with pytest.raises(InvalidClauseOrderError, match=re.escape(message)):
        create(node("Movie", name="m")).match(node("Person", name="p"))
    with pytest.raises(InvalidClauseOrderError, match=re.escape(message)):
        Statement((CreateClause((node("Movie", name="m"),)), MatchClause((node("Person", name="p"),))))


def test_update_without_preceding_clause_rejected_identically() -> None:
    from cypher_dsl import assign
    from cypher_dsl.statements.builder import StatementBuilder

    message = "SET needs a preceding clause that binds its target. Start with match(), create() or merge()."
    with pytest.raises(InvalidClauseOrderError, match=re.escape(message)):
        StatementBuilder().set_(assign(_variable("m"), {}))
    with pytest.raises(InvalidClauseOrderError, match=re.escape(message)):
        Statement((SetClause((assign(_variable("m"), {}),)),))


def test_return_twice_rejected_identically() -> None:
    message = "RETURN must be the final clause and can appear only once in a statement."
    with pytest.raises(InvalidClauseOrderError, match=re.escape(message)):
        match(node("Movie", name="m")).returning("m").returning("m")
    with pytest.raises(InvalidClauseOrderError, match=re.escape(message)):
        Statement(
            (
                MatchClause((node("Movie", name="m"),)),
                ReturnClause((_variable("m"),)),
                ReturnClause((_variable("m"),)),
            )
        )

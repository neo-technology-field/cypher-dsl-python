"""
Write-clause declaration classification.

A write pattern both declares names and refers to nodes an earlier clause bound. The
classification is shared so the renderer and the statement validator apply the same rules.
"""

from __future__ import annotations

import pytest

from cypher_dsl import match, merge, node
from cypher_dsl.errors import DslError
from cypher_dsl.statements.scope import DeclarationRole, _Scope, classify_write_declarations


def test_create_endpoint_reference_is_classified_after_a_match() -> None:
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    query = match(person, movie).create(person.relationship_to(movie, "ACTED_IN"))
    statement = query.build()
    create_clause = statement.clauses[-1]
    scope = _Scope((), False, (("p", person), ("m", movie)))
    declarations = classify_write_declarations(scope, create_clause.patterns, "CREATE")
    roles = {
        declaration.node.variable.value: declaration.role for declaration in declarations if declaration.node.variable
    }
    assert roles == {"p": DeclarationRole.REFERENCE, "m": DeclarationRole.REFERENCE}


def test_conflicting_bound_endpoint_still_fails_during_construction() -> None:
    first = node("Person", name="n")
    conflicting = node("Movie", name="n")
    with pytest.raises(DslError, match="conflicting declaration"):
        merge(first.relationship_to(conflicting, "KNOWS")).build()

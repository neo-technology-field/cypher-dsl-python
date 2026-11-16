# Ported from the Java Cypher-DSL test suite (neo4j/cypher-dsl, Apache-2.0).
# Traced source: CypherIT. Rewritten for pytest.
"""
MATCH and OPTIONAL MATCH clauses with their attached filters.

A filter belongs to the clause that owns it. The tests pin clause-local placement,
predicate combination, pattern-map restrictions and the point at which a read query is
still incomplete.
"""

from __future__ import annotations

import pytest

from cypher_dsl import (
    BinaryOperation,
    Configuration,
    Language,
    MatchClause,
    Renderer,
    StatementBuilder,
    condition,
    match,
    name,
    node,
    optional_match,
    param,
)
from cypher_dsl.errors import DslError, EmptyPatternError, InvalidClauseOrderError


def test_match_renders_patterns_but_returns_references():
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    acted = person.relationship_to(movie, "ACTED_IN", name="r")
    query = match(acted).where(movie["released"] < param("year", 2000)).returning(person, movie)
    result = Renderer.get(Configuration(server_version="5.26")).render(query)
    assert result.cypher == "MATCH (p:Person)-[r:ACTED_IN]->(m:Movie) WHERE m.released < $year RETURN p, m"
    assert result.parameters == {"year": 2000}


def test_label_and_variable_names_cannot_become_clauses():
    movie = node("Odd`Label", name="odd name")
    text = Renderer.get(Configuration(server_version="5.26")).render(match(movie).returning(movie)).cypher
    assert text == "MATCH (`odd name`:`Odd``Label`) RETURN `odd name`"


def test_optional_match_keeps_its_filter():
    movie = node("Movie", name="m")
    query = optional_match(movie).where(movie["released"] < 2000).returning(movie)
    clause = query.clauses[0]
    assert isinstance(clause, MatchClause)
    assert clause.optional is True
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "OPTIONAL MATCH (m:Movie) WHERE m.released < 2000 RETURN m"
    )


def test_consecutive_filters_combine_into_one_attached_predicate():
    movie = node("Movie", name="m")
    query = match(movie).where(movie["released"] > 1990).where(movie["released"] < 2000).returning(movie)
    clause = query.clauses[0]
    assert isinstance(clause, MatchClause)
    assert clause.where is not None
    assert isinstance(clause.where.predicate, BinaryOperation)
    rendered = Renderer.get(Configuration(server_version="5.26")).render(query)
    assert rendered.cypher == "MATCH (m:Movie) WHERE m.released > 1990 AND m.released < 2000 RETURN m"
    assert rendered.cypher.count("WHERE") == 1


def test_a_filter_stays_with_the_optional_clause_it_follows():
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    query = (
        match(person)
        .optional_match(person.relationship_to(movie, "ACTED_IN", name="r"))
        .where(movie["released"] > 2000)
        .returning(person)
    )
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (p:Person) OPTIONAL MATCH (p:Person)-[r:ACTED_IN]->(m:Movie) WHERE m.released > 2000 RETURN p"
    )


def test_multiple_patterns_and_reused_endpoints_render_in_order():
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    query = match(person.relationship_to(movie, "ACTED_IN", name="r"), movie).returning(person, movie)
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (p:Person)-[r:ACTED_IN]->(m:Movie), (m:Movie) RETURN p, m"
    )


def test_empty_match_is_rejected():
    with pytest.raises(EmptyPatternError):
        match()
    with pytest.raises(EmptyPatternError):
        optional_match()
    with pytest.raises(EmptyPatternError):
        StatementBuilder().match()


def test_match_rejects_a_whole_map_expression_as_pattern_properties():
    with pytest.raises(DslError, match="whole-map"):
        match(node("Movie", name="m", properties=param("props", {"title": "x"})))
    with pytest.raises(DslError, match="whole-map"):
        match(
            node("Person", name="p").relationship_to(node("Movie", name="m"), "ACTED_IN", properties=param("props", {}))
        )


def test_match_only_statement_cannot_be_finalised():
    with pytest.raises(DslError, match="RETURN"):
        match(node("Movie", name="m")).build()


def test_a_filter_cannot_follow_return():
    movie = node("Movie", name="m")
    with pytest.raises(InvalidClauseOrderError):
        match(movie).returning(movie).where(movie["released"] > 2000)


def test_a_filter_needs_an_owning_clause():
    with pytest.raises(DslError, match="MATCH"):
        StatementBuilder().where(condition(name("flag")))


def test_pattern_parameters_and_unbound_names_are_reported_per_render():
    movie = node("Movie", name="m", properties={"title": param("title")})
    query = match(movie).where(movie["released"] < param("year", 2000)).returning(movie)
    renderer = Renderer.get(Configuration(server_version="5.26"))
    first = renderer.render(query)
    assert first.cypher == "MATCH (m:Movie {title: $title}) WHERE m.released < $year RETURN m"
    assert first.parameters == {"year": 2000}
    assert first.unbound_parameters == frozenset({"title"})
    second = renderer.render(query)
    assert second.cypher == first.cypher
    assert second.parameters == first.parameters
    assert second.parameters is not first.parameters


def test_optional_match_without_a_filter_renders_no_where():
    movie = node("Movie", name="m")
    query = optional_match(movie).returning(movie)
    clause = query.clauses[0]
    assert isinstance(clause, MatchClause)
    assert clause.where is None
    assert (
        Renderer.get(Configuration(server_version="5.26")).render(query).cypher == "OPTIONAL MATCH (m:Movie) RETURN m"
    )


def test_upstream_cypher5_prefix_on_simple_statements():
    n = node("Movie", name="n")
    statement = match(n).returning(n).build()
    configuration = Configuration(server_version="5.26", language=Language.CYPHER_5, always_escape_names=False)
    assert Renderer.get(configuration).render(statement).cypher == "CYPHER 5 MATCH (n:Movie) RETURN n"


def test_upstream_optional_match_followed_by_a_match():
    # Pinned: OPTIONAL MATCH (b:`Bike`) MATCH (u:`User`), (o:`U`) WHERE u.a IS NULL RETURN b
    bike = node("Bike", name="b")
    user = node("User", name="u")
    other = node("U", name="o")
    query = optional_match(bike).match(user, other).where(user["a"] == None).returning(bike)  # noqa: E711
    rendered = Renderer.get(Configuration(server_version="5.26", always_escape_names=True)).render(query)
    assert rendered.cypher == (
        "OPTIONAL MATCH (`b`:`Bike`) MATCH (`u`:`User`), (`o`:`U`) WHERE `u`.`a` IS NULL RETURN `b`"
    )

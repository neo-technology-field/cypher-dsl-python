# Ported from the Java Cypher-DSL test suite (neo4j/cypher-dsl, Apache-2.0).
# Traced sources: CypherIT, Cypher5IT. Rewritten for pytest.
"""
Read composition across MATCH, WITH and RETURN.

The composition tests exercise the read grammar as a whole: several matching parts, a WITH
boundary, attached filters and projection modifiers. They also pin that a shared prefix is
a value, so two branches can extend it without one branch changing the other.
"""

from __future__ import annotations

import pytest

from cypher_dsl import (
    Configuration,
    Language,
    Renderer,
    Statement,
    StatementBuilder,
    count,
    desc,
    lit,
    match,
    name,
    node,
    param,
    raw,
    union,
)
from cypher_dsl.errors import DslError


def test_no_decoration_api_remains_on_the_facade() -> None:
    import cypher_dsl

    for removed in ("explain", "profile", "DecoratedQuery", "QueryDecoration"):
        assert removed not in cypher_dsl.__all__
        assert not hasattr(cypher_dsl, removed)


def test_the_fluent_construction_stage_is_a_statement_builder() -> None:
    import cypher_dsl

    assert "StatementBuilder" in cypher_dsl.__all__
    assert "Query" not in cypher_dsl.__all__
    assert not hasattr(cypher_dsl, "Query")

    person = node("Person", name="p")
    builder = match(person).where(person["email"] == param("email")).returning(person["display_name"])
    assert isinstance(builder, StatementBuilder)
    assert isinstance(builder.build(), Statement)


def test_a_read_composes_matching_parts_around_a_with_boundary():
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    query = (
        match(person)
        .with_(person)
        .match(person.relationship_to(movie, "ACTED_IN", name="r"))
        .where(movie["released"] > 2000)
        .returning(person["given"], movie["title"])
        .order_by(desc(movie["released"]))
        .limit(10)
    )
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (p:Person) WITH p "
        "MATCH (p:Person)-[r:ACTED_IN]->(m:Movie) WHERE m.released > 2000 "
        "RETURN p.given, m.title ORDER BY m.released DESC LIMIT 10"
    )


def test_optional_match_after_with_keeps_its_own_filter():
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    query = (
        match(person)
        .with_(person)
        .optional_match(person.relationship_to(movie, "DIRECTED", name="d"))
        .where(movie["released"] > 2000)
        .returning(person, movie)
    )
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (p:Person) WITH p OPTIONAL MATCH (p:Person)-[d:DIRECTED]->(m:Movie) WHERE m.released > 2000 RETURN p, m"
    )


def test_two_with_boundaries_project_one_name_each_time():
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    query = (
        match(person.relationship_to(movie, "ACTED_IN", name="r"))
        .with_(person["given"].alias("actor"))
        .with_(name("actor"))
        .returning(name("actor"))
    )
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (p:Person)-[r:ACTED_IN]->(m:Movie) WITH p.given AS actor WITH actor RETURN actor"
    )


def test_a_with_can_project_an_aggregate_for_the_next_part():
    person = node("Person", name="p")
    query = match(person).with_(count(person).alias("people")).returning(name("people")).order_by(desc(name("people")))
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (p:Person) WITH count(p) AS people RETURN people ORDER BY people DESC"
    )


def test_with_distinct_paginates_and_filters():
    movie = node("Movie", name="m")
    query = (
        match(movie)
        .with_(movie["released"].alias("year"))
        .distinct()
        .order_by(name("year"))
        .skip(param("offset", 5))
        .limit(10)
        .where(name("year") > 2000)
        .returning(name("year"))
    )
    rendered = Renderer.get(Configuration(server_version="5.26")).render(query)
    assert rendered.cypher == (
        "MATCH (m:Movie) WITH DISTINCT m.released AS year ORDER BY year "
        "SKIP $offset LIMIT 10 WHERE year > 2000 RETURN year"
    )
    assert rendered.parameters == {"offset": 5}


def test_a_raw_with_projection_defers_scope_checks():
    movie = node("Movie", name="m")
    query = match(movie).with_(raw("m")).returning(movie["title"])
    assert (
        Renderer.get(Configuration(server_version="5.26")).render(query).cypher
        == "MATCH (m:Movie) WITH m RETURN m.title"
    )


def test_a_discarded_reference_is_rejected_when_composing():
    movie = node("Movie", name="m")
    query = match(movie).with_(movie["released"].alias("year"))
    with pytest.raises(DslError, match="not in scope"):
        query.returning(movie["title"])


def test_a_composed_read_renders_stably():
    movie = node("Movie", name="m")
    query = (
        match(movie).with_(movie["title"].alias("title")).returning(name("title")).order_by(name("title")).limit(lit(5))
    )
    renderer = Renderer.get(Configuration(server_version="5.26"))
    first = renderer.render(query)
    second = renderer.render(query.build())
    assert (
        first.cypher == second.cypher == ("MATCH (m:Movie) WITH m.title AS title RETURN title ORDER BY title LIMIT 5")
    )
    assert first.parameters is not second.parameters


def test_a_later_match_property_cannot_use_a_discarded_name():
    movie = node("Movie", name="m")
    person = node("Person", name="p")
    query = match(movie, person).with_(person)
    with pytest.raises(DslError, match="not in scope"):
        query.match(node("Person", name="q", properties={"source": movie["title"]}))


def test_a_later_optional_match_property_cannot_use_a_discarded_name():
    movie = node("Movie", name="m")
    person = node("Person", name="p")
    query = match(movie, person).with_(person)
    with pytest.raises(DslError, match="not in scope"):
        query.optional_match(node("Person", name="q", properties={"source": movie["title"]}))


def test_a_later_match_property_can_use_a_name_the_new_pattern_binds():
    movie = node("Movie", name="m")
    person = node("Person", name="p")
    query = (
        match(movie, person)
        .with_(person)
        .match(node("Person", name="q", properties={"source": name("q")["email"]}))
        .returning(name("q"))
    )
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (m:Movie), (p:Person) WITH p MATCH (q:Person {source: q.email}) RETURN q"
    )


def test_upstream_union_does_not_repeat_the_language_prefix():
    bike = node("Bike", name="b")
    parts = [
        match(bike).where(bike[key] == value).returning(bike) for key, value in (("a", "A"), ("b", "B"), ("c", "C"))
    ]
    configuration = Configuration(server_version="5.26", language=Language.CYPHER_5, always_escape_names=False)
    assert Renderer.get(configuration).render(union(*parts)).cypher == (
        "CYPHER 5 MATCH (b:Bike) WHERE b.a = 'A' RETURN b "
        "UNION MATCH (b:Bike) WHERE b.b = 'B' RETURN b "
        "UNION MATCH (b:Bike) WHERE b.c = 'C' RETURN b"
    )


def test_upstream_union_of_three_matches():
    # Pinned: MATCH (b:`Bike`) WHERE b.a = 'A' RETURN b UNION ...
    bike = node("Bike", name="b")
    parts = [
        match(bike).where(bike[key] == value).returning(bike) for key, value in (("a", "A"), ("b", "B"), ("c", "C"))
    ]
    rendered = Renderer.get(Configuration(server_version="5.26", always_escape_names=True)).render(union(*parts))
    assert rendered.cypher == (
        "MATCH (`b`:`Bike`) WHERE `b`.`a` = 'A' RETURN `b` "
        "UNION MATCH (`b`:`Bike`) WHERE `b`.`b` = 'B' RETURN `b` "
        "UNION MATCH (`b`:`Bike`) WHERE `b`.`c` = 'C' RETURN `b`"
    )


def test_upstream_union_all_of_two_matches():
    # Pinned: MATCH (b:`Bike`) WHERE b.a = 'A' RETURN b UNION ALL MATCH (b:`Bike`) WHERE b.b = 'B' RETURN b
    bike = node("Bike", name="b")
    parts = [match(bike).where(bike[key] == value).returning(bike) for key, value in (("a", "A"), ("b", "B"))]
    rendered = Renderer.get(Configuration(server_version="5.26", always_escape_names=True)).render(
        union(*parts, all=True)
    )
    assert rendered.cypher == (
        "MATCH (`b`:`Bike`) WHERE `b`.`a` = 'A' RETURN `b` UNION ALL MATCH (`b`:`Bike`) WHERE `b`.`b` = 'B' RETURN `b`"
    )

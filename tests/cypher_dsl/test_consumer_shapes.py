"""
Consumer-shaped statement contracts for an OGM-free caller.

Each test builds the statement a persistence layer would send and pins the query text and
the bindings together. These are static contracts: there is no model class, driver
session, schema installation or execution anywhere in this module. The shapes cover
representative reads, relationship writes, upserts, counts and bulk operations that a
persistence layer can rely on without depending on an OGM.
"""

from __future__ import annotations

import pytest

from cypher_dsl import (
    Configuration,
    Language,
    Rendered,
    Renderer,
    assign,
    count,
    desc,
    match,
    merge,
    name,
    node,
    param,
    union,
    unwind,
    update_properties,
)
from cypher_dsl.errors import DslError


def _render(query, **configuration: object) -> Rendered:
    configuration.setdefault("server_version", "5.26")
    return Renderer.get(Configuration(**configuration)).render(query)


def _endpoints():
    person = node("Person", name="p", properties={"uid": param("person_uid", "p1")})
    movie = node("Movie", name="m", properties={"uid": param("movie_uid", "m1")})
    acted = person.relationship_to(movie, "ACTED_IN", name="r")
    return person, movie, acted


def test_relationship_write_matches_endpoints_before_merging():
    person, movie, acted = _endpoints()
    query = match(person, movie).merge(acted).returning(count(acted).alias("connections"))
    rendered = _render(query)
    assert rendered.parameters == {"person_uid": "p1", "movie_uid": "m1"}
    assert rendered.cypher == (
        "MATCH (p:Person {uid: $person_uid}), (m:Movie {uid: $movie_uid}) "
        "MERGE (p)-[r:ACTED_IN]->(m) RETURN count(r) AS connections"
    )


def test_an_anonymous_relationship_cannot_be_counted():
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    anonymous = person.relationship_to(movie, "ACTED_IN")
    with pytest.raises(DslError, match="anonymous relationship"):
        count(anonymous)


def test_a_merge_names_only_the_endpoints_that_were_already_bound():
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    acted = person.relationship_to(movie, "ACTED_IN", name="r")
    assert _render(match(person).merge(acted)).cypher == "MATCH (p:Person) MERGE (p)-[r:ACTED_IN]->(m:Movie)"


def test_bound_endpoint_state_is_held_per_statement_scope():
    person, movie, acted = _endpoints()
    bound = match(person, movie).merge(acted).returning(count(acted).alias("connections"))
    bare = merge(acted).returning(count(acted).alias("connections"))
    renderer = Renderer.get(Configuration(server_version="5.26"))

    first = renderer.render(bound)
    second = renderer.render(bound)
    assert first.cypher == second.cypher
    assert first.cypher.endswith("MERGE (p)-[r:ACTED_IN]->(m) RETURN count(r) AS connections")

    assert renderer.render(union(bare, bound)).cypher.startswith(
        "MERGE (p:Person {uid: $person_uid})-[r:ACTED_IN]->(m:Movie {uid: $movie_uid}) "
        "RETURN count(r) AS connections UNION "
    )
    assert renderer.render(union(bare, bound)).parameters == {"person_uid": "p1", "movie_uid": "m1"}
    assert renderer.render(union(bound, bare)).cypher.endswith(
        "UNION MERGE (p:Person {uid: $person_uid})-[r:ACTED_IN]->(m:Movie {uid: $movie_uid}) "
        "RETURN count(r) AS connections"
    )


def test_a_conflicting_merge_declaration_is_not_suppressed():
    person = node("Person", name="p", properties={"uid": 1})
    employee = node("Employee", name="p", properties={"uid": 1})
    with pytest.raises(DslError, match="bound standalone"):
        match(person).merge(employee)


@pytest.mark.parametrize(
    ("server_version", "language", "expected"),
    [
        (
            "5.26",
            Language.AUTO,
            "MATCH (m:Movie) WHERE m.released < $year RETURN m.title",
        ),
        (
            "5.26",
            Language.NONE,
            "MATCH (m:Movie) WHERE m.released < $year RETURN m.title",
        ),
        (
            "5.26",
            Language.CYPHER_5,
            "CYPHER 5 MATCH (m:Movie) WHERE m.released < $year RETURN m.title",
        ),
        (
            "2026.10",
            Language.CYPHER_25,
            "CYPHER 25 MATCH (m:Movie) WHERE m.released < $year RETURN m.title",
        ),
    ],
)
def test_the_language_prefix_matrix_is_explicit(server_version, language, expected):
    movie = node("Movie", name="m")
    query = match(movie).where(movie["released"] < param("year", 2000)).returning(movie["title"])
    rendered = _render(query, server_version=server_version, language=language)
    assert rendered.cypher == expected
    assert rendered.parameters == {"year": 2000}


def test_optional_relationship_filtering_stays_on_the_optional_match():
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    query = (
        match(person)
        .optional_match(person.relationship_to(movie, "ACTED_IN", name="r"))
        .where(movie["released"] > param("year", 2000))
        .returning(person["given"], movie["title"])
    )
    rendered = _render(query)
    assert rendered.cypher == (
        "MATCH (p:Person) OPTIONAL MATCH (p:Person)-[r:ACTED_IN]->(m:Movie) "
        "WHERE m.released > $year RETURN p.given, m.title"
    )
    assert rendered.parameters == {"year": 2000}


def test_ordering_by_an_alias_uses_the_projected_name():
    movie = node("Movie", name="m")
    query = match(movie).returning(movie["title"].alias("title"), movie["released"]).order_by(desc(name("title")))
    assert _render(query).cypher == "MATCH (m:Movie) RETURN m.title AS title, m.released ORDER BY title DESC"


def test_a_count_projection_uses_the_named_relationship():
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    acted = person.relationship_to(movie, "ACTED_IN", name="r")
    query = match(person).optional_match(acted).returning(person["given"], count(name("r")).alias("films"))
    assert _render(query).cypher == (
        "MATCH (p:Person) OPTIONAL MATCH (p:Person)-[r:ACTED_IN]->(m:Movie) RETURN p.given, count(r) AS films"
    )


def test_a_node_save_merges_the_identity_and_splits_the_updates():
    person = node("Person", name="p", properties={"uid": param("person_uid", "p1")})
    query = (
        merge(person)
        .on_create(assign(person["given"], param("given", "Ada")), assign(person["created"], param("now", "t0")))
        .on_match(assign(person["seen"], param("now", "t0")))
        .returning(person["uid"])
    )
    rendered = _render(query)
    assert rendered.cypher == (
        "MERGE (p:Person {uid: $person_uid}) "
        "ON CREATE SET p.given = $given, p.created = $now "
        "ON MATCH SET p.seen = $now RETURN p.uid"
    )
    assert rendered.parameters == {"person_uid": "p1", "given": "Ada", "now": "t0"}


def test_a_return_less_delete_is_a_complete_statement():
    person = node("Person", name="p", properties={"uid": param("person_uid", "p1")})
    rendered = _render(match(person).detach_delete(person))
    assert rendered.cypher == "MATCH (p:Person {uid: $person_uid}) DETACH DELETE p"
    assert rendered.parameters == {"person_uid": "p1"}


def test_a_bulk_create_uses_one_rows_parameter():
    rows = [{"uid": "p1", "given": "Ada"}, {"uid": "p2", "given": "Grace"}]
    row = name("row")
    person = node("Person", name="p", properties={"uid": row["uid"], "given": row["given"]})
    query = unwind(param("rows", rows), row).create(person).returning(person["uid"])
    rows[0]["given"] = "Changed"
    rendered = _render(query)
    assert rendered.cypher == (
        "UNWIND $rows AS `row` CREATE (p:Person {uid: `row`.uid, given: `row`.given}) RETURN p.uid"
    )
    assert rendered.parameters == {"rows": [{"uid": "p1", "given": "Ada"}, {"uid": "p2", "given": "Grace"}]}


def test_a_relationship_upsert_carries_merge_actions_and_bindings():
    person = node("Person", name="p", properties={"uid": param("person_uid", "p1")})
    movie = node("Movie", name="m", properties={"uid": param("movie_uid", "m1")})
    acted = person.relationship_to(movie, "ACTED_IN", name="r", properties={"since": param("since", 1999)})
    query = (
        merge(acted)
        .on_create(assign(acted["created"], param("now", "t0")))
        .on_match(assign(acted["seen"], param("now", "t0")))
    )
    rendered = _render(query)
    assert rendered.cypher == (
        "MERGE (p:Person {uid: $person_uid})-[r:ACTED_IN {since: $since}]->(m:Movie {uid: $movie_uid}) "
        "ON CREATE SET r.created = $now ON MATCH SET r.seen = $now"
    )
    assert rendered.parameters == {"person_uid": "p1", "since": 1999, "movie_uid": "m1", "now": "t0"}


def test_a_map_patch_updates_only_the_given_properties():
    person = node("Person", name="p", properties={"uid": param("person_uid", "p1")})
    query = match(person).set_(update_properties(person, param("patch", {"given": "Ada"})))
    rendered = _render(query)
    assert rendered.cypher == "MATCH (p:Person {uid: $person_uid}) SET p += $patch"
    assert rendered.parameters == {"person_uid": "p1", "patch": {"given": "Ada"}}

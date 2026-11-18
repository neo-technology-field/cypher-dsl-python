"""Reference rendering: a pattern restating a bound node renders as the bare variable."""

from __future__ import annotations

from cypher_dsl import (
    Configuration,
    Renderer,
    exists,
    lit,
    match,
    name,
    node,
    path_pattern,
)
from cypher_dsl.statements.frames import DeclarationRole, ScopeFrame

PERSON = node("Person", name="p")
DOG = node("Dog", name="d")
MOVIE = node("Movie", name="m")


def _rendered(statement) -> str:
    renderer = Renderer.get(Configuration(server_version="5.26"))
    return renderer.render(statement).cypher


def test_a_restated_endpoint_renders_as_the_bare_variable() -> None:
    statement = match(PERSON).optional_match(PERSON.relationship_to(MOVIE, "DIRECTED")).returning(PERSON["uid"])
    assert _rendered(statement) == ("MATCH (p:Person) OPTIONAL MATCH (p)-[:DIRECTED]->(m:Movie) RETURN p.uid")


def test_first_declarations_and_anonymous_nodes_render_in_full() -> None:
    chain = PERSON.relationship_to(node("Dog"), "HAS_DOG")
    assert _rendered(match(chain).returning(PERSON["uid"])) == ("MATCH (p:Person)-[:HAS_DOG]->(:Dog) RETURN p.uid")


def test_a_differing_declaration_stays_a_filter() -> None:
    manager = node("Manager", name="p")
    statement = match(PERSON).optional_match(manager.relationship_to(MOVIE, "DIRECTED")).returning(PERSON["uid"])
    assert _rendered(statement) == ("MATCH (p:Person) OPTIONAL MATCH (p:Manager)-[:DIRECTED]->(m:Movie) RETURN p.uid")


def test_a_restated_property_map_stays_a_filter() -> None:
    keyed = node("Person", name="p", properties={"uid": lit("p1")})
    statement = match(PERSON).optional_match(keyed.relationship_to(MOVIE, "DIRECTED")).returning(PERSON["uid"])
    assert _rendered(statement) == (
        "MATCH (p:Person) OPTIONAL MATCH (p:Person {uid: 'p1'})-[:DIRECTED]->(m:Movie) RETURN p.uid"
    )


def test_a_within_clause_restatement_renders_bare() -> None:
    statement = match(PERSON, PERSON.relationship_to(MOVIE, "DIRECTED")).returning(PERSON["uid"])
    assert _rendered(statement) == ("MATCH (p:Person), (p)-[:DIRECTED]->(m:Movie) RETURN p.uid")


def test_a_path_pattern_restatement_renders_bare() -> None:
    works_for = PERSON.relationship_to(node("Person", properties={"uid": lit("p1")}), "WORKS_FOR")
    statement = match(PERSON).where(path_pattern(works_for)).returning(PERSON["uid"])
    assert _rendered(statement) == ("MATCH (p:Person) WHERE (p)-[:WORKS_FOR]->(:Person {uid: 'p1'}) RETURN p.uid")


def test_a_path_pattern_differing_declaration_keeps_its_labels() -> None:
    manager = node("Manager", name="p")
    works_for = manager.relationship_to(node("Person", properties={"uid": lit("p1")}), "WORKS_FOR")
    statement = match(PERSON).where(path_pattern(works_for)).returning(PERSON["uid"])
    assert _rendered(statement) == (
        "MATCH (p:Person) WHERE (p:Manager)-[:WORKS_FOR]->(:Person {uid: 'p1'}) RETURN p.uid"
    )


def test_a_where_chain_does_not_disturb_the_clause_classification() -> None:
    works_for = PERSON.relationship_to(node("Person", properties={"uid": lit("p1")}), "WORKS_FOR")
    statement = match(PERSON, DOG).where(path_pattern(works_for)).returning(PERSON["uid"])
    assert _rendered(statement) == (
        "MATCH (p:Person), (d:Dog) WHERE (p)-[:WORKS_FOR]->(:Person {uid: 'p1'}) RETURN p.uid"
    )


def test_a_with_filter_chain_keeps_its_labels_without_a_carried_identity() -> None:
    # The filter of a first WITH after an open MATCH reads names without their node
    # identities, so the conservative guard renders the restatement in full.
    works_for = PERSON.relationship_to(node("Person", properties={"uid": lit("p1")}), "WORKS_FOR")
    statement = match(PERSON).with_(PERSON).where(path_pattern(works_for)).returning(PERSON["uid"])
    assert _rendered(statement) == (
        "MATCH (p:Person) WITH p WHERE (p:Person)-[:WORKS_FOR]->(:Person {uid: 'p1'}) RETURN p.uid"
    )


def test_the_comparison_base_survives_a_differing_occurrence() -> None:
    # After a differing occurrence, the incoming binding stays the comparison base:
    # the differing form keeps its labels, and restating the incoming form is vacuous.
    manager = node("Manager", name="p")
    restatement = node("Person", name="p")
    statement = match(PERSON).optional_match(manager.relationship_to(restatement, "DIRECTED")).returning(PERSON["uid"])
    assert _rendered(statement) == ("MATCH (p:Person) OPTIONAL MATCH (p:Manager)-[:DIRECTED]->(p) RETURN p.uid")


def test_a_subquery_body_restates_the_enclosing_name_bare() -> None:
    body = match(PERSON.relationship_to(DOG, "HAS_DOG"))
    statement = match(PERSON).where(exists(body)).returning(PERSON["name"])
    assert _rendered(statement) == ("MATCH (p:Person) WHERE EXISTS { MATCH (p)-[:HAS_DOG]->(d:Dog) } RETURN p.`name`")


def test_a_call_body_restates_the_imported_name_bare() -> None:
    body = match(PERSON.relationship_to(MOVIE, "ACTED_IN")).returning(MOVIE["title"].alias("title")).build()
    statement = match(PERSON).call(body, imports=("p",)).returning(name("title"))
    assert _rendered(statement) == (
        "MATCH (p:Person) CALL (p) { MATCH (p)-[:ACTED_IN]->(m:Movie) RETURN m.title AS title } RETURN title"
    )


def test_a_bound_name_without_node_identity_stays_declared() -> None:
    from cypher_dsl.statements.rules.match import _classify_match_declarations

    bound_without_identity = ScopeFrame(names=("p",))
    assert _classify_match_declarations(bound_without_identity, (PERSON,))[0].role is DeclarationRole.DECLARE

    bound_with_identity = ScopeFrame(names=("p",), bindings=(("p", PERSON),))
    assert _classify_match_declarations(bound_with_identity, (PERSON,))[0].role is DeclarationRole.REFERENCE
    differing = _classify_match_declarations(bound_with_identity, (node("Manager", name="p"),))
    assert differing[0].role is DeclarationRole.DECLARE

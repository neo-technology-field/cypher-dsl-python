"""Path pattern expressions: construction, rendering and scope contracts."""

from __future__ import annotations

import pytest

from cypher_dsl import (
    Configuration,
    PathPatternExpression,
    Renderer,
    exists,
    label,
    lit,
    match,
    node,
    param,
    path_pattern,
    structurally_equal,
)
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.base import Precedence
from cypher_dsl.expressions.operators import Condition
from cypher_dsl.statements.analysis import analyse

PERSON = node("Person", name="p")
MANAGER = node("Person", name="m")


def test_accepts_a_relationship_chain() -> None:
    works_for = PERSON.relationship_to(MANAGER, "WORKS_FOR")
    expression = path_pattern(works_for)
    assert isinstance(expression, PathPatternExpression)
    assert expression.pattern is works_for
    assert expression.children() == (works_for,)


def test_the_expression_is_a_condition() -> None:
    expression = path_pattern(PERSON.relationship_to(MANAGER, "WORKS_FOR"))
    assert isinstance(expression, Condition)
    assert expression.precedence is Precedence.ATOM


def test_local_names_is_empty() -> None:
    expression = path_pattern(PERSON.relationship_to(node("Person"), "WORKS_FOR"))
    assert expression.local_names() == ()


def test_structural_equality_compares_the_chain() -> None:
    one = path_pattern(PERSON.relationship_to(node("Person"), "WORKS_FOR"))
    two = path_pattern(PERSON.relationship_to(node("Person"), "WORKS_FOR"))
    assert structurally_equal(one, two)
    assert not structurally_equal(one, path_pattern(PERSON.relationship_to(node("Person"), "REPORTS_TO")))


def test_rejects_a_bare_node_pattern() -> None:
    with pytest.raises(DslError, match="has_label"):
        path_pattern(PERSON)


def test_rejects_an_unsupported_input() -> None:
    with pytest.raises(DslError, match="relationship chain"):
        path_pattern("WORKS_FOR")


def test_renders_the_cheat_sheet_example() -> None:
    works_for = PERSON.relationship_to(node("Person", properties={"uid": lit("p1")}), "WORKS_FOR")
    statement = match(PERSON).where(path_pattern(works_for)).returning(PERSON["uid"])
    rendered = Renderer.get(Configuration(server_version="5.26")).render(statement)
    assert rendered.cypher == ("MATCH (p:Person) WHERE (p:Person)-[:WORKS_FOR]->(:Person {uid: 'p1'}) RETURN p.uid")


def test_renders_every_direction() -> None:
    renderer = Renderer.get(Configuration(server_version="5.26"))
    outgoing = (
        match(PERSON).where(path_pattern(PERSON.relationship_to(node("Person"), "WORKS_FOR"))).returning(PERSON["uid"])
    )
    incoming = (
        match(PERSON)
        .where(path_pattern(PERSON.relationship_from(node("Person"), "WORKS_FOR")))
        .returning(PERSON["uid"])
    )
    undirected = (
        match(PERSON)
        .where(path_pattern(PERSON.relationship_with(node("Person"), "WORKS_FOR")))
        .returning(PERSON["uid"])
    )
    assert renderer.render(outgoing).cypher == (
        "MATCH (p:Person) WHERE (p:Person)-[:WORKS_FOR]->(:Person) RETURN p.uid"
    )
    assert renderer.render(incoming).cypher == (
        "MATCH (p:Person) WHERE (p:Person)<-[:WORKS_FOR]-(:Person) RETURN p.uid"
    )
    assert renderer.render(undirected).cypher == (
        "MATCH (p:Person) WHERE (p:Person)-[:WORKS_FOR]-(:Person) RETURN p.uid"
    )


def test_renders_an_untyped_relationship() -> None:
    statement = match(PERSON).where(path_pattern(PERSON.relationship_to(node("Person")))).returning(PERSON["uid"])
    rendered = Renderer.get(Configuration(server_version="5.26")).render(statement)
    assert rendered.cypher == "MATCH (p:Person) WHERE (p:Person)-->(:Person) RETURN p.uid"


def test_renders_a_type_expression() -> None:
    types = label("ACTED_IN") | label("DIRECTED")
    statement = match(PERSON).where(path_pattern(PERSON.relationship_to(node("Movie"), types))).returning(PERSON["uid"])
    rendered = Renderer.get(Configuration(server_version="5.26")).render(statement)
    assert rendered.cypher == ("MATCH (p:Person) WHERE (p:Person)-[:ACTED_IN|DIRECTED]->(:Movie) RETURN p.uid")


def test_renders_relationship_details() -> None:
    works_for = PERSON.relationship_to(node("Person"), "WORKS_FOR", properties={"since": param("year", 2015)})
    statement = match(PERSON).where(path_pattern(works_for)).returning(PERSON["uid"])
    rendered = Renderer.get(Configuration(server_version="5.26")).render(statement)
    assert rendered.cypher == ("MATCH (p:Person) WHERE (p:Person)-[:WORKS_FOR {since: $year}]->(:Person) RETURN p.uid")
    assert rendered.parameters == {"year": 2015}


def test_reuses_the_match_pattern_object() -> None:
    report = PERSON.relationship_to(MANAGER, "WORKS_FOR", name="r")
    statement = match(report).where(path_pattern(report)).returning(PERSON["uid"])
    rendered = Renderer.get(Configuration(server_version="5.26")).render(statement)
    assert rendered.cypher == (
        "MATCH (p:Person)-[r:WORKS_FOR]->(m:Person) WHERE (p:Person)-[r:WORKS_FOR]->(m:Person) RETURN p.uid"
    )


def test_combines_with_other_predicates() -> None:
    works_for = PERSON.relationship_to(node("Person"), "WORKS_FOR")
    statement = match(PERSON).where(~path_pattern(works_for) & (PERSON["age"] > 30)).returning(PERSON["uid"])
    rendered = Renderer.get(Configuration(server_version="5.26")).render(statement)
    assert rendered.cypher == (
        "MATCH (p:Person) WHERE NOT (p:Person)-[:WORKS_FOR]->(:Person) AND p.age > 30 RETURN p.uid"
    )


def test_quotes_a_reserved_map_key() -> None:
    works_for = PERSON.relationship_to(node("Person", properties={"name": lit("Alice")}), "WORKS_FOR")
    statement = match(PERSON).where(path_pattern(works_for)).returning(PERSON["uid"])
    rendered = Renderer.get(Configuration(server_version="5.26")).render(statement)
    assert rendered.cypher == (
        "MATCH (p:Person) WHERE (p:Person)-[:WORKS_FOR]->(:Person {`name`: 'Alice'}) RETURN p.uid"
    )


def test_quotes_every_identifier_when_requested() -> None:
    works_for = PERSON.relationship_to(node("Person", properties={"uid": lit("p1")}), "WORKS_FOR")
    statement = match(PERSON).where(path_pattern(works_for)).returning(PERSON["uid"])
    rendered = Renderer.get(Configuration(server_version="5.26", always_escape_names=True)).render(statement)
    assert rendered.cypher == (
        "MATCH (`p`:`Person`) WHERE (`p`:`Person`)-[:`WORKS_FOR`]->(:`Person` {`uid`: 'p1'}) RETURN `p`.`uid`"
    )


def test_pretty_keeps_a_short_predicate_on_one_line() -> None:
    works_for = PERSON.relationship_to(node("Person"), "WORKS_FOR")
    statement = match(PERSON).where(path_pattern(works_for)).returning(PERSON["uid"])
    rendered = Renderer.get(Configuration(server_version="5.26", pretty_print=True)).render(statement)
    assert rendered.cypher == ("MATCH (p:Person) WHERE (p:Person)-[:WORKS_FOR]->(:Person) RETURN p.uid")


def test_pretty_puts_a_long_predicate_on_its_own_line() -> None:
    works_for = PERSON.relationship_to(
        node("Person", properties={"uid": lit("p1")}),
        "WORKS_FOR",
        properties={"since": param("year", 2015)},
    ).relationship_to(node("Person", properties={"uid": lit("p2")}), "REPORTS_TO")
    statement = match(PERSON).where(path_pattern(works_for)).returning(PERSON["uid"])
    rendered = Renderer.get(Configuration(server_version="5.26", pretty_print=True)).render(statement)
    assert rendered.cypher == (
        "MATCH (p:Person)\n"
        "  WHERE (p:Person)-[:WORKS_FOR {since: $year}]->(:Person {uid: 'p1'})"
        "-[:REPORTS_TO]->(:Person {uid: 'p2'})\n"
        "RETURN p.uid"
    )


def test_rejects_a_name_a_with_boundary_dropped() -> None:
    works_for = PERSON.relationship_to(MANAGER, "WORKS_FOR")
    statement = (
        match(PERSON, MANAGER)
        .with_(PERSON)
        .with_(PERSON)
        .where(path_pattern(works_for))
        .returning(PERSON["uid"])
        .build()
    )
    with pytest.raises(DslError, match="not in scope"):
        Renderer.get(Configuration(server_version="5.26")).render(statement)


def test_rejects_a_name_an_import_does_not_supply() -> None:
    works_for = PERSON.relationship_to(MANAGER, "WORKS_FOR")
    body = match(PERSON).where(path_pattern(works_for)).returning(PERSON["uid"]).build()
    statement = match(PERSON).call(body, imports=("p",)).returning(PERSON["uid"]).build()
    with pytest.raises(DslError, match="not in scope"):
        Renderer.get(Configuration(server_version="5.26")).render(statement)


def test_rejects_a_relationship_name_an_import_does_not_supply() -> None:
    report = PERSON.relationship_to(MANAGER, "WORKS_FOR", name="r")
    body = match(PERSON).where(path_pattern(report)).returning(PERSON["uid"]).build()
    statement = match(PERSON).call(body, imports=("p",)).returning(PERSON["uid"]).build()
    with pytest.raises(DslError, match="not in scope"):
        Renderer.get(Configuration(server_version="5.26")).render(statement)


def test_rejects_a_name_an_exists_body_cannot_see() -> None:
    works_for = PERSON.relationship_to(MANAGER, "WORKS_FOR")
    body = match(PERSON).where(path_pattern(works_for)).returning(PERSON["uid"]).build()
    statement = match(PERSON).where(exists(body)).returning(PERSON["uid"]).build()
    with pytest.raises(DslError, match="not in scope"):
        Renderer.get(Configuration(server_version="5.26")).render(statement)


def test_tolerates_an_unprovable_name_in_an_open_frame() -> None:
    works_for = PERSON.relationship_to(node("Person", name="q"), "WORKS_FOR")
    statement = match(PERSON).where(path_pattern(works_for)).returning(PERSON["uid"])
    rendered = Renderer.get(Configuration(server_version="5.26")).render(statement)
    assert rendered.cypher == ("MATCH (p:Person) WHERE (p:Person)-[:WORKS_FOR]->(q:Person) RETURN p.uid")


def test_records_no_requirements() -> None:
    works_for = PERSON.relationship_to(node("Person"), "WORKS_FOR")
    statement = match(PERSON).where(path_pattern(works_for)).returning(PERSON["uid"]).build()
    assert analyse(statement).requirements == ()


def test_renders_under_a_with_filter() -> None:
    works_for = PERSON.relationship_to(node("Person"), "WORKS_FOR")
    statement = match(PERSON).with_(PERSON).where(path_pattern(works_for)).returning(PERSON["uid"])
    rendered = Renderer.get(Configuration(server_version="5.26")).render(statement)
    assert rendered.cypher == ("MATCH (p:Person) WITH p WHERE (p:Person)-[:WORKS_FOR]->(:Person) RETURN p.uid")


def test_renders_under_a_procedure_filter() -> None:
    works_for = PERSON.relationship_to(node("Person"), "WORKS_FOR")
    statement = (
        match(PERSON)
        .call_procedure("db.labels")
        .yielding("label")
        .where(path_pattern(works_for))
        .returning(PERSON["uid"])
    )
    rendered = Renderer.get(Configuration(server_version="5.26")).render(statement)
    assert rendered.cypher == (
        "MATCH (p:Person) CALL db.labels() YIELD `label` WHERE (p:Person)-[:WORKS_FOR]->(:Person) RETURN p.uid"
    )


def test_rejects_a_bare_expression_as_a_return_item() -> None:
    works_for = PERSON.relationship_to(node("Person"), "WORKS_FOR")
    with pytest.raises(DslError, match="not a boolean position"):
        match(PERSON).returning(path_pattern(works_for))


def test_rejects_a_bare_expression_as_a_with_item() -> None:
    works_for = PERSON.relationship_to(node("Person"), "WORKS_FOR")
    with pytest.raises(DslError, match="not a boolean position"):
        match(PERSON).with_(path_pattern(works_for).alias("works"))


def test_rejects_an_aliased_bare_expression() -> None:
    works_for = PERSON.relationship_to(node("Person"), "WORKS_FOR")
    with pytest.raises(DslError, match="not a boolean position"):
        match(PERSON).returning(path_pattern(works_for).alias("works"))


def test_projects_the_negated_form() -> None:
    works_for = PERSON.relationship_to(node("Person"), "WORKS_FOR")
    statement = match(PERSON).returning((~path_pattern(works_for)).alias("alone"))
    rendered = Renderer.get(Configuration(server_version="5.26")).render(statement)
    assert rendered.cypher == ("MATCH (p:Person) RETURN NOT (p:Person)-[:WORKS_FOR]->(:Person) AS alone")

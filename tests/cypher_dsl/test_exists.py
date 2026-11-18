"""EXISTS subquery expressions: construction, body shape, name binding and analysis contracts."""

from __future__ import annotations

import pytest

from cypher_dsl import (
    Configuration,
    ExistsExpression,
    Renderer,
    Statement,
    assign,
    call_procedure,
    count,
    create,
    exists,
    lit,
    match,
    name,
    node,
    param,
    union,
    unwind,
    with_,
)
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.operators import Condition
from cypher_dsl.features import Capability
from cypher_dsl.statements.analysis import analyse

PERSON = node("Person", name="p")
DOG = node("Dog", name="d")


def test_accepts_a_finalised_statement() -> None:
    body = match(DOG).returning(DOG["name"]).build()
    expression = exists(body)
    assert isinstance(expression, ExistsExpression)
    assert expression.subquery is body
    assert expression.children() == (body,)


def test_finalises_a_builder() -> None:
    expression = exists(match(PERSON.relationship_to(DOG, "HAS_DOG")))
    assert isinstance(expression.subquery, Statement)
    assert len(expression.subquery.clauses) == 1


def test_wraps_a_pattern_element_in_a_match_body() -> None:
    expression = exists(PERSON.relationship_to(node("Dog"), "HAS_DOG"))
    assert len(expression.subquery.clauses) == 1
    rendered = Renderer.get(Configuration(server_version="5.26")).render(
        match(PERSON).where(expression).returning(PERSON["name"])
    )
    assert rendered.cypher == ("MATCH (p:Person) WHERE EXISTS { MATCH (p:Person)-[:HAS_DOG]->(:Dog) } RETURN p.`name`")


def test_rejects_an_unsupported_input() -> None:
    with pytest.raises(DslError, match="EXISTS accepts statements, unions"):
        exists("db.labels")


def test_rejects_an_unfinalised_body_through_the_class() -> None:
    with pytest.raises(DslError, match="finalised statement or union"):
        ExistsExpression(match(DOG))


def test_rejects_a_write_clause_in_the_body() -> None:
    with pytest.raises(DslError, match="non-writing subquery"):
        exists(match(PERSON).set_(assign(PERSON["age"], 36)))


def test_rejects_a_nested_call_body_that_writes() -> None:
    body = create(node("Clone", properties={"uid": name("item")})).build()
    with pytest.raises(DslError, match="non-writing subquery"):
        exists(unwind(param("rows"), name("item")).call(body, imports=("item",)))


def test_rejects_inner_transactions_in_the_body() -> None:
    body = create(node("Clone", properties={"uid": name("item")})).build()
    with pytest.raises(DslError, match="non-writing subquery"):
        exists(unwind(param("rows"), name("item")).call(body, imports=("item",), in_transactions=100))


def test_local_names_covers_every_binding_in_the_body() -> None:
    body = match(DOG).with_(lit("Ozzy").alias("dog_name"))
    assert exists(body).local_names() == ("d", "dog_name")


def test_local_names_survives_a_discarding_with() -> None:
    body = match(DOG).with_(lit("Ozzy").alias("dog_name")).match(PERSON)
    names = exists(body).local_names()
    assert "d" in names
    assert "dog_name" in names
    assert "p" in names


def test_the_expression_is_a_condition() -> None:
    expression = exists(match(DOG))
    assert isinstance(expression, Condition)
    assert isinstance(~expression, Condition)
    assert isinstance(expression & (PERSON["age"] > 30), Condition)


def _analysed(statement):
    return analyse(statement.build() if hasattr(statement, "build") else statement)


def test_body_reads_a_name_the_enclosing_pattern_binds() -> None:
    body = match(DOG).where(DOG["name"] == PERSON["nickname"])
    statement = match(PERSON).where(exists(body)).returning(PERSON["name"])
    analysis = _analysed(statement)
    assert analysis.requirements == ()


def test_body_referencing_an_unknown_name_rejects() -> None:
    ghost = name("ghost")
    body = match(DOG).where(DOG["name"] == ghost)
    with pytest.raises(DslError, match="not in scope"):
        _analysed(match(PERSON).where(exists(body)).returning(PERSON["name"]))


def test_a_with_filter_reads_the_alias_it_introduces() -> None:
    body = match(DOG).where(DOG["name"] == name("age"))
    statement = match(PERSON).with_(PERSON["age"].alias("age")).where(exists(body)).returning(name("age"))
    _analysed(statement)


def test_a_with_filter_behind_a_closed_frame_reads_the_alias_it_introduces() -> None:
    body = match(DOG).where(DOG["name"] == name("age"))
    statement = match(PERSON).with_(PERSON).with_(PERSON["age"].alias("age")).where(exists(body)).returning(name("age"))
    _analysed(statement)


def test_a_distinct_first_with_filter_still_name_checks_the_body() -> None:
    """A restricting projection knows its names without an incoming frame, so the body is checked."""
    body = match(DOG).where(DOG["name"] == name("ghost"))
    _analysed(with_(lit("x").alias("k")).where(exists(body)).returning(name("k")))
    with pytest.raises(DslError, match="refers to 'ghost'"):
        with_(lit("x").alias("k")).distinct().where(exists(body)).returning(name("k"))
    with pytest.raises(DslError, match="refers to 'ghost'"):
        with_(count(lit(1)).alias("n")).where(exists(body)).returning(name("n"))


def test_a_procedure_filter_reads_the_names_it_yields() -> None:
    body = match(PERSON).where(PERSON["name"] == name("label"))
    statement = call_procedure("db.labels").yielding("label").where(exists(body)).returning(name("label"))
    _analysed(statement)


def test_a_return_item_reads_pre_return_names() -> None:
    body = match(DOG).where(DOG["name"] == PERSON["nickname"])
    statement = match(PERSON).returning(PERSON["name"], exists(body).alias("has_dog"))
    _analysed(statement)


def test_a_nested_exists_analyses() -> None:
    toy = node("Toy", name="t")
    inner = exists(match(toy).where(toy["name"] == DOG["name"]))
    body = match(DOG).where(inner)
    statement = match(PERSON).where(exists(body)).returning(PERSON["name"])
    _analysed(statement)


def test_outer_reference_after_a_discarding_body_with_rejects() -> None:
    # The documented limit: a body WITH that drops an enclosing name does not keep it
    # visible. The rejection carries the standard WITH remedy: project the name through.
    cat = node("Cat", name="c")
    with pytest.raises(DslError, match="not in scope"):
        body = match(DOG).with_(DOG).match(cat).where(cat["name"] == PERSON["nickname"])
        match(PERSON).where(exists(body)).returning(PERSON["name"])


def test_a_body_with_introducing_a_new_name_analyses() -> None:
    body = (
        match(PERSON.relationship_to(DOG, "HAS_DOG"))
        .with_(lit("Ozzy").alias("dog_name"))
        .where(DOG["name"] == name("dog_name"))
    )
    _analysed(match(PERSON).where(exists(body)).returning(PERSON["name"]))


def test_shadowing_an_outer_name_is_tolerated() -> None:
    # A documented limit: the server rejects the shadowing, the library does not.
    body = match(DOG).with_(lit("Ozzy").alias("p"))
    _analysed(match(PERSON).where(exists(body)).returning(PERSON["name"]))


def test_a_read_call_body_analyses_and_records_its_requirement() -> None:
    inner = match(DOG).returning(DOG["name"].alias("dog_name"))
    body = match(PERSON).call(inner, imports=("p",))
    statement = match(PERSON).where(exists(body)).returning(PERSON["name"])
    analysis = _analysed(statement)
    assert any(requirement.capability is Capability.SCOPE_CLAUSES for requirement in analysis.requirements)


def test_a_union_body_analyses_without_returns() -> None:
    body = union(
        match(PERSON.relationship_to(node("Dog"), "HAS_DOG")),
        match(PERSON.relationship_to(node("Cat"), "HAS_CAT")),
    )
    statement = match(PERSON).where(exists(body)).returning(PERSON["name"])
    _analysed(statement)


def test_a_union_body_with_returns_in_every_branch_analyses() -> None:
    cat = node("Cat", name="c")
    body = union(match(DOG).returning(DOG["name"]), match(cat).returning(cat["name"]))
    statement = match(PERSON).where(exists(body)).returning(PERSON["name"])
    _analysed(statement)


def _rendered(statement, pretty=False):
    renderer = Renderer.get(Configuration(server_version="5.26", pretty_print=pretty))
    return renderer.render(statement)


def test_renders_in_a_where_clause() -> None:
    body = match(PERSON.relationship_to(DOG, "HAS_DOG")).where(DOG["name"] == param("dog_name"))
    statement = match(PERSON).where(exists(body)).returning(PERSON["name"])
    assert _rendered(statement).cypher == (
        "MATCH (p:Person) WHERE EXISTS { MATCH (p:Person)-[:HAS_DOG]->(d:Dog) WHERE d.`name` = $dog_name }"
        " RETURN p.`name`"
    )


def test_renders_a_bare_pattern_body() -> None:
    keeps_dog = exists(PERSON.relationship_to(node("Dog"), "HAS_DOG"))
    statement = match(PERSON).returning(PERSON["name"], keeps_dog.alias("keeps_dog"))
    assert _rendered(statement).cypher == (
        "MATCH (p:Person) RETURN p.`name`, EXISTS { MATCH (p:Person)-[:HAS_DOG]->(:Dog) } AS keeps_dog"
    )


def test_combines_with_boolean_operators() -> None:
    body = match(PERSON.relationship_to(DOG, "HAS_DOG"))
    statement = match(PERSON).where(~exists(body) & (PERSON["age"] > 30)).returning(PERSON["name"])
    assert _rendered(statement).cypher == (
        "MATCH (p:Person) WHERE NOT EXISTS { MATCH (p:Person)-[:HAS_DOG]->(d:Dog) } AND p.age > 30 RETURN p.`name`"
    )


def test_renders_as_a_comparison_operand() -> None:
    body = match(PERSON.relationship_to(DOG, "HAS_DOG"))
    statement = match(PERSON).where(exists(body) == lit(True)).returning(PERSON["name"])
    assert _rendered(statement).cypher == (
        "MATCH (p:Person) WHERE EXISTS { MATCH (p:Person)-[:HAS_DOG]->(d:Dog) } = true RETURN p.`name`"
    )


def test_renders_a_union_body() -> None:
    body = union(
        match(PERSON.relationship_to(node("Dog"), "HAS_DOG")),
        match(PERSON.relationship_to(node("Cat"), "HAS_CAT")),
    )
    statement = match(PERSON).where(exists(body)).returning(PERSON["name"])
    assert _rendered(statement).cypher == (
        "MATCH (p:Person) WHERE EXISTS { MATCH (p:Person)-[:HAS_DOG]->(:Dog)"
        " UNION MATCH (p:Person)-[:HAS_CAT]->(:Cat) } RETURN p.`name`"
    )


def test_body_parameters_are_collected() -> None:
    body = match(PERSON.relationship_to(DOG, "HAS_DOG")).where(DOG["name"] == param("dog_name", "Rex"))
    other = match(PERSON.relationship_to(node("Cat"), "HAS_CAT")).where(PERSON["nickname"] == param("cat_name"))
    statement = match(PERSON).where(exists(body) | exists(other)).returning(PERSON["name"])
    rendered = _rendered(statement)
    assert rendered.parameters == {"dog_name": "Rex"}
    assert rendered.unbound_parameters == frozenset({"cat_name"})


def test_pretty_print_breaks_the_body_out() -> None:
    body = match(PERSON.relationship_to(DOG, "HAS_DOG")).where(DOG["name"] == param("dog_name"))
    statement = match(PERSON).where(exists(body)).returning(PERSON["name"])
    assert _rendered(statement, pretty=True).cypher == (
        "MATCH (p:Person)\n"
        "  WHERE EXISTS {\n"
        "    MATCH (p:Person)-[:HAS_DOG]->(d:Dog) WHERE d.`name` = $dog_name\n"
        "  }\n"
        "RETURN p.`name`"
    )


def test_pretty_print_breaks_an_exists_projection() -> None:
    body = match(PERSON.relationship_to(DOG, "HAS_DOG"))
    statement = match(PERSON).returning(PERSON["uid"], exists(body).alias("keeps_dog"))
    rendered = _rendered(statement, pretty=True)
    assert rendered.cypher == (
        "MATCH (p:Person)\nRETURN p.uid, EXISTS {\n  MATCH (p:Person)-[:HAS_DOG]->(d:Dog)\n} AS keeps_dog"
    )


def test_pretty_print_breaks_a_union_that_holds_an_exists() -> None:
    statement = union(
        match(PERSON).where(exists(PERSON.relationship_to(node("Dog"), "HAS_DOG"))).returning(PERSON["uid"]),
        match(DOG).returning(DOG["uid"]),
    )
    assert _rendered(statement, pretty=True).cypher == (
        "MATCH (p:Person)\n"
        "  WHERE EXISTS {\n"
        "    MATCH (p:Person)-[:HAS_DOG]->(:Dog)\n"
        "  }\n"
        "RETURN p.uid\n"
        "UNION\n"
        "MATCH (d:Dog)\n"
        "RETURN d.uid"
    )


def test_no_language_prefix_under_auto() -> None:
    body = match(PERSON.relationship_to(DOG, "HAS_DOG"))
    statement = match(PERSON).where(exists(body)).returning(PERSON["name"])
    assert _rendered(statement).cypher.startswith("MATCH")

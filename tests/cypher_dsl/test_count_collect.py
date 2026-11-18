"""COUNT and COLLECT subquery expressions: construction, body shape and analysis contracts.

The COUNT scenarios port org.neo4j.cypherdsl.core.ExpressionsIT.java and the COLLECT
scenarios the nested class CollectSubqueries of org.neo4j.cypherdsl.core.SubqueriesIT.java,
both from neo4j/cypher-dsl at commit d3b17e42. Where an expectation renders the MATCH
keyword where upstream prints a bare pattern, the deviation is stated beside it: this
library always names the MATCH keyword.
"""

from __future__ import annotations

import pytest

from cypher_dsl import (
    CollectExpression,
    Comparison,
    Configuration,
    CountExpression,
    Rendered,
    Renderer,
    Statement,
    SubqueryExpression,
    assign,
    asterisk,
    collect_subquery,
    count_subquery,
    create,
    exists,
    in_,
    lit,
    match,
    name,
    node,
    param,
    union,
    unwind,
)
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.operators import Condition
from cypher_dsl.features import Capability
from cypher_dsl.statements.analysis import Analysis, analyse

PERSON = node("Person", name="p")
DOG = node("Dog", name="d")


def test_exists_expression_is_a_subquery_expression() -> None:
    expression = exists(match(DOG))
    assert isinstance(expression, SubqueryExpression)
    assert expression.keyword == "EXISTS"


def test_the_base_class_rejects_direct_construction() -> None:
    with pytest.raises(DslError, match="must state its keyword"):
        SubqueryExpression(match(DOG).returning(DOG["name"]).build())


def test_count_accepts_a_finalised_statement() -> None:
    body = match(DOG).returning(DOG["name"]).build()
    expression = count_subquery(body)
    assert isinstance(expression, CountExpression)
    assert expression.subquery is body
    assert expression.children() == (body,)
    assert expression.keyword == "COUNT"


def test_count_finalises_a_builder_without_a_final_return() -> None:
    expression = count_subquery(match(PERSON.relationship_to(DOG, "HAS_DOG")))
    assert isinstance(expression.subquery, Statement)
    assert len(expression.subquery.clauses) == 1


def test_count_wraps_a_pattern_element_in_a_match_body() -> None:
    expression = count_subquery(PERSON.relationship_to(node("Dog"), "HAS_DOG"))
    assert len(expression.subquery.clauses) == 1


def test_count_rejects_an_unsupported_input() -> None:
    with pytest.raises(DslError, match="COUNT accepts statements, unions"):
        count_subquery("db.labels")


def test_count_rejects_an_unfinalised_body_through_the_class() -> None:
    with pytest.raises(DslError, match="finalised statement or union"):
        CountExpression(match(DOG))


def test_count_rejects_a_write_clause_in_the_body() -> None:
    with pytest.raises(DslError, match="non-writing subquery"):
        count_subquery(match(PERSON).set_(assign(PERSON["age"], 36)))


def test_count_rejects_a_nested_call_body_that_writes() -> None:
    body = create(node("Clone", properties={"uid": name("item")})).build()
    with pytest.raises(DslError, match="non-writing subquery"):
        count_subquery(unwind(param("rows"), name("item")).call(body, imports=("item",)))


def test_count_rejects_inner_transactions_in_the_body() -> None:
    body = create(node("Clone", properties={"uid": name("item")})).build()
    with pytest.raises(DslError, match="non-writing subquery"):
        count_subquery(unwind(param("rows"), name("item")).call(body, imports=("item",), in_transactions=100))


def test_count_local_names_covers_every_binding_in_the_body() -> None:
    body = match(DOG).with_(lit("Ozzy").alias("dog_name"))
    assert count_subquery(body).local_names() == ("d", "dog_name")


def test_count_is_a_value_expression_not_a_condition() -> None:
    expression = count_subquery(match(DOG))
    assert isinstance(expression, SubqueryExpression)
    assert not isinstance(expression, Condition)
    assert isinstance(expression > lit(1), Comparison)


def test_collect_accepts_a_single_column_return() -> None:
    body = match(DOG).returning(DOG["name"]).build()
    expression = collect_subquery(body)
    assert isinstance(expression, CollectExpression)
    assert expression.subquery is body
    assert expression.children() == (body,)
    assert expression.keyword == "COLLECT"


def test_collect_accepts_an_aliased_column_and_a_distinct_return() -> None:
    aliased = match(DOG).returning(DOG["name"].alias("dog_name")).build()
    distinct = match(DOG).returning(DOG["name"]).distinct().build()
    assert isinstance(collect_subquery(aliased), CollectExpression)
    assert isinstance(collect_subquery(distinct), CollectExpression)


def test_collect_accepts_a_union_body_with_one_column_per_branch() -> None:
    cat = node("Cat", name="c")
    body = union(match(DOG).returning(DOG["name"]), match(cat).returning(cat["name"]))
    assert isinstance(collect_subquery(body), CollectExpression)


def test_collect_rejects_a_body_without_a_final_return() -> None:
    with pytest.raises(DslError, match="ends in RETURN"):
        collect_subquery(match(DOG))


def test_an_empty_hand_built_body_is_rejected_before_the_collect_shape_check() -> None:
    # Statement validates its clause sequence, so an empty body cannot reach the
    # COLLECT branch checks; it fails at construction with the statement diagnostic.
    with pytest.raises(DslError, match="needs at least one clause"):
        CollectExpression(Statement(()))


def test_collect_rejects_a_pattern_element_through_the_return_rule() -> None:
    with pytest.raises(DslError, match="ends in RETURN"):
        collect_subquery(PERSON.relationship_to(node("Dog"), "HAS_DOG"))


def test_collect_rejects_a_multi_column_return() -> None:
    body = match(PERSON).returning(PERSON["name"], PERSON["nickname"])
    with pytest.raises(DslError, match="exactly one column, not 2"):
        collect_subquery(body)


def test_collect_rejects_return_asterisk() -> None:
    body = match(PERSON).returning(asterisk())
    with pytest.raises(DslError, match="not RETURN \\*"):
        collect_subquery(body)


def test_collect_rejects_a_union_where_no_branch_returns() -> None:
    body = union(match(DOG), match(PERSON))
    with pytest.raises(DslError, match="ends in RETURN"):
        collect_subquery(body)


def test_collect_rejects_a_write_clause_in_the_body() -> None:
    with pytest.raises(DslError, match="non-writing subquery"):
        collect_subquery(match(PERSON).set_(assign(PERSON["age"], 36)))


def test_collect_rejects_an_unsupported_input() -> None:
    with pytest.raises(DslError, match="COLLECT accepts statements, unions"):
        collect_subquery("db.labels")


def test_collect_local_names_covers_every_binding_in_the_body() -> None:
    body = match(DOG).returning(DOG["name"].alias("dog_name"))
    assert collect_subquery(body).local_names() == ("d", "dog_name")


def _rendered(statement, pretty=False) -> Rendered:
    renderer = Renderer.get(Configuration(server_version="5.26", pretty_print=pretty))
    return renderer.render(statement)


def test_renders_count_in_a_where_comparison() -> None:
    body = match(PERSON.relationship_to(DOG, "HAS_DOG"))
    statement = match(PERSON).where(count_subquery(body) > lit(1)).returning(PERSON["name"])
    assert _rendered(statement).cypher == (
        "MATCH (p:Person) WHERE COUNT { MATCH (p)-[:HAS_DOG]->(d:Dog) } > 1 RETURN p.`name`"
    )


def test_renders_count_with_a_discarded_return() -> None:
    # Upstream prints COUNT { (person)-[:HAS_DOG]->(dog) } here; this library always
    # names the MATCH keyword and keeps the body's RETURN.
    body = match(PERSON.relationship_to(DOG, "HAS_DOG")).returning(DOG["name"])
    statement = match(PERSON).where(count_subquery(body) == lit(1)).returning(PERSON["name"])
    assert _rendered(statement).cypher == (
        "MATCH (p:Person) WHERE COUNT { MATCH (p)-[:HAS_DOG]->(d:Dog) RETURN d.`name` } = 1 RETURN p.`name`"
    )


def test_renders_count_in_a_return_projection() -> None:
    body = match(PERSON.relationship_to(DOG, "HAS_DOG"))
    statement = match(PERSON).returning(PERSON["name"], count_subquery(body).alias("how_many"))
    assert _rendered(statement).cypher == (
        "MATCH (p:Person) RETURN p.`name`, COUNT { MATCH (p)-[:HAS_DOG]->(d:Dog) } AS how_many"
    )


def test_renders_count_in_a_set_assignment() -> None:
    body = match(PERSON.relationship_to(node("Dog"), "HAS_DOG"))
    statement = (
        match(PERSON)
        .where(PERSON["name"] == lit("Peter"))
        .set_(assign(PERSON["how_many_dogs"], count_subquery(body)))
        .returning(PERSON["how_many_dogs"])
    )
    assert _rendered(statement).cypher == (
        "MATCH (p:Person) WHERE p.`name` = 'Peter'"
        " SET p.how_many_dogs = COUNT { MATCH (p)-[:HAS_DOG]->(:Dog) }"
        " RETURN p.how_many_dogs"
    )


def test_renders_collect_in_a_where_membership() -> None:
    body = match(PERSON.relationship_to(DOG, "HAS_DOG")).returning(DOG["name"])
    statement = match(PERSON).where(in_(lit("Ozzy"), collect_subquery(body))).returning(PERSON["name"])
    assert _rendered(statement).cypher == (
        "MATCH (p:Person) WHERE 'Ozzy' IN COLLECT { MATCH (p)-[:HAS_DOG]->(d:Dog) RETURN d.`name` } RETURN p.`name`"
    )


def test_renders_collect_in_a_set_assignment() -> None:
    body = match(PERSON.relationship_to(DOG, "HAS_DOG")).returning(DOG["name"])
    statement = (
        match(PERSON)
        .where(PERSON["name"] == lit("Peter"))
        .set_(assign(PERSON["dog_names"], collect_subquery(body)))
        .returning(PERSON["dog_names"])
    )
    assert _rendered(statement).cypher == (
        "MATCH (p:Person) WHERE p.`name` = 'Peter'"
        " SET p.dog_names = COLLECT { MATCH (p)-[:HAS_DOG]->(d:Dog) RETURN d.`name` }"
        " RETURN p.dog_names"
    )


def test_renders_a_collect_union_body() -> None:
    cat = node("Cat", name="c")
    body = union(
        match(PERSON.relationship_to(DOG, "HAS_DOG")).returning(DOG["name"]),
        match(PERSON.relationship_to(cat, "HAS_CAT")).returning(cat["name"]),
    )
    statement = match(PERSON).returning(PERSON["name"], collect_subquery(body).alias("pet_names"))
    assert _rendered(statement).cypher == (
        "MATCH (p:Person) RETURN p.`name`, COLLECT {"
        " MATCH (p)-[:HAS_DOG]->(d:Dog) RETURN d.`name`"
        " UNION MATCH (p)-[:HAS_CAT]->(c:Cat) RETURN c.`name`"
        " } AS pet_names"
    )


def test_renders_a_collect_nested_in_a_count_body() -> None:
    dogs = match(PERSON.relationship_to(DOG, "HAS_DOG")).returning(DOG["name"])
    body = match(PERSON).returning(collect_subquery(dogs).alias("dog_names"))
    statement = match(PERSON).where(count_subquery(body) > lit(1)).returning(PERSON["name"])
    assert _rendered(statement).cypher == (
        "MATCH (p:Person) WHERE COUNT {"
        " MATCH (p) RETURN COLLECT { MATCH (p)-[:HAS_DOG]->(d:Dog) RETURN d.`name` } AS dog_names"
        " } > 1 RETURN p.`name`"
    )


def test_body_parameters_are_collected_through_both_expressions() -> None:
    counted = match(PERSON.relationship_to(DOG, "HAS_DOG")).where(DOG["name"] == param("dog_name", "Rex"))
    collected = (
        match(PERSON.relationship_to(node("Cat"), "HAS_CAT"))
        .where(PERSON["nickname"] == param("cat_name"))
        .returning(PERSON["nickname"])
    )
    statement = match(PERSON).returning(
        PERSON["name"],
        count_subquery(counted).alias("dog_count"),
        collect_subquery(collected).alias("cat_names"),
    )
    rendered = _rendered(statement)
    assert rendered.parameters == {"dog_name": "Rex"}
    assert rendered.unbound_parameters == frozenset({"cat_name"})


def _analysed(statement) -> Analysis:
    return analyse(statement.build() if hasattr(statement, "build") else statement)


def test_count_body_reads_a_name_the_enclosing_pattern_binds() -> None:
    body = match(DOG).where(DOG["name"] == PERSON["nickname"])
    statement = match(PERSON).where(count_subquery(body) > lit(1)).returning(PERSON["name"])
    assert _analysed(statement).requirements == ()


def test_count_body_referencing_an_unknown_name_rejects() -> None:
    body = match(DOG).where(DOG["name"] == name("ghost"))
    with pytest.raises(DslError, match="not in scope"):
        _analysed(match(PERSON).where(count_subquery(body) > lit(1)).returning(PERSON["name"]))


def test_a_body_return_name_stays_inside_the_expression() -> None:
    # A MATCH frame stays open for CALL imports, so only a body read is name-checked.
    # The binding body is the left operand because children are validated left to
    # right: the reading body must be checked after it, so a body walk that merged its
    # names back into the enclosing frame would hide the leak from this assertion.
    alias_body = match(DOG).returning(DOG["name"].alias("dog_name"))
    reader_body = match(DOG).where(DOG["name"] == name("dog_name"))
    statement = match(PERSON).where(count_subquery(alias_body) > count_subquery(reader_body)).returning(PERSON["name"])
    with pytest.raises(DslError, match="not in scope"):
        _analysed(statement)


def test_collect_body_reads_the_enclosing_scope() -> None:
    body = match(DOG).where(DOG["name"] == PERSON["nickname"]).returning(DOG["name"])
    statement = match(PERSON).returning(PERSON["name"], collect_subquery(body).alias("dogs"))
    _analysed(statement)


def test_a_correlated_body_pattern_restates_an_enclosing_name() -> None:
    body = match(PERSON.relationship_to(DOG, "HAS_DOG")).returning(DOG["name"])
    statement = match(PERSON).where(count_subquery(body) > lit(1)).returning(PERSON["name"])
    _analysed(statement)


def test_count_union_bodies_analyse() -> None:
    without = union(
        match(PERSON.relationship_to(node("Dog"), "HAS_DOG")),
        match(PERSON.relationship_to(node("Cat"), "HAS_CAT")),
    )
    _analysed(match(PERSON).where(count_subquery(without) > lit(1)).returning(PERSON["name"]))
    cat = node("Cat", name="c")
    with_returns = union(match(DOG).returning(DOG["name"]), match(cat).returning(cat["name"]))
    _analysed(match(PERSON).where(count_subquery(with_returns) > lit(1)).returning(PERSON["name"]))


def test_a_nested_call_body_records_its_requirement() -> None:
    inner = match(DOG).returning(DOG["name"].alias("dog_name"))
    body = match(PERSON).call(inner, imports=("p",))
    statement = match(PERSON).where(count_subquery(body) > lit(1)).returning(PERSON["name"])
    analysis = _analysed(statement)
    assert any(requirement.capability is Capability.SCOPE_CLAUSES for requirement in analysis.requirements)


def test_nested_subquery_expressions_analyse() -> None:
    dogs = match(PERSON.relationship_to(DOG, "HAS_DOG")).returning(DOG["name"])
    body = match(PERSON).returning(collect_subquery(dogs).alias("dog_names"))
    statement = match(PERSON).where(count_subquery(body) > lit(1)).returning(PERSON["name"])
    _analysed(statement)


def test_pretty_print_breaks_a_count_body_out() -> None:
    body = match(PERSON.relationship_to(DOG, "HAS_DOG")).where(DOG["name"] == param("dog_name"))
    statement = match(PERSON).where(count_subquery(body) > lit(1)).returning(PERSON["name"])
    assert _rendered(statement, pretty=True).cypher == (
        "MATCH (p:Person)\n"
        "  WHERE COUNT {\n"
        "    MATCH (p)-[:HAS_DOG]->(d:Dog) WHERE d.`name` = $dog_name\n"
        "  } > 1\n"
        "RETURN p.`name`"
    )


def test_pretty_print_breaks_a_collect_projection() -> None:
    body = match(PERSON.relationship_to(DOG, "HAS_DOG")).returning(DOG["name"])
    statement = match(PERSON).returning(PERSON["name"], collect_subquery(body).alias("dog_names"))
    assert _rendered(statement, pretty=True).cypher == (
        "MATCH (p:Person)\nRETURN p.`name`, COLLECT {\n  MATCH (p)-[:HAS_DOG]->(d:Dog) RETURN d.`name`\n} AS dog_names"
    )

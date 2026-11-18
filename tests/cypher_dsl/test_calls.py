# Scenarios are ported from the Java Cypher-DSL test suite (neo4j/cypher-dsl, Apache-2.0):
# SubqueriesIT.java, nested class ResultReturningSubqueries, method importingVariablesShouldWork,
# and ProcedureCallsIT.java, methods yieldItemsRenamed, where and withThanReturningInQuery.
# They are adapted for pytest and for this library's builder surface and rendered text. All other
# tests in this module are local contract tests.
"""CALL subqueries and procedure calls: construction, rendering, scope and target contracts."""

from __future__ import annotations

from textwrap import dedent

import pytest

from cypher_dsl import (
    AliasedExpression,
    Configuration,
    Language,
    Literal,
    Renderer,
    Statement,
    SymbolicName,
    Variable,
    assign,
    asterisk,
    call,
    count,
    create,
    fn,
    lit,
    match,
    merge,
    name,
    node,
    optional_call,
    param,
    raw,
    returning,
    union,
    unwind,
    with_,
)
from cypher_dsl.clauses.call import (
    ProcedureCallClause,
    SubqueryCallClause,
    _coerce_import,
    call_procedure,
    optional_call_procedure,
)
from cypher_dsl.errors import ConflictingParameterError, DslError, InvalidClauseOrderError, InvalidIdentifierError
from cypher_dsl.expressions.operators import BinaryOperation
from cypher_dsl.features import Capability
from cypher_dsl.statements.analysis import analyse

PERSON = node("Person", name="p")
MOVIE = node("Movie", name="m")

LABELS = ("db", "labels")


def _returning_title_body():
    return match(MOVIE).returning(MOVIE["title"].alias("title")).build()


def test_clause_holds_its_parts() -> None:
    body = _returning_title_body()
    imported = name("p")
    clause = SubqueryCallClause(body, (imported,))
    assert clause.subquery is body
    assert len(clause.imports) == 1
    assert clause.imports[0] is imported
    children = clause.children()
    assert len(children) == 1
    assert children[0] is body


def test_clause_requires_a_finalised_body() -> None:
    with pytest.raises(DslError, match="finalised statement or union"):
        SubqueryCallClause("db.labels")


def test_clause_requires_tuple_imports() -> None:
    with pytest.raises(DslError, match="must be a tuple"):
        SubqueryCallClause(_returning_title_body(), [name("p")])


def test_clause_rejects_non_variable_imports() -> None:
    with pytest.raises(DslError, match="need variables"):
        SubqueryCallClause(_returning_title_body(), (42,))


def test_clause_rejects_named_imports_combined_with_import_all() -> None:
    with pytest.raises(DslError, match="not both"):
        SubqueryCallClause(_returning_title_body(), (name("p"),), import_all=True)


def test_clause_rejects_boolean_flags_of_the_wrong_type() -> None:
    for field in ("import_all", "optional", "in_transactions"):
        with pytest.raises(DslError, match="boolean choice"):
            SubqueryCallClause(_returning_title_body(), (), **{field: "yes"})


def test_clause_rejects_row_count_without_transactions() -> None:
    with pytest.raises(DslError, match="belongs to IN TRANSACTIONS"):
        SubqueryCallClause(_returning_title_body(), (), of_rows=lit(2))


def test_clause_rejects_row_counts_that_are_not_expressions() -> None:
    with pytest.raises(DslError, match="needs an expression"):
        SubqueryCallClause(_returning_title_body(), (), in_transactions=True, of_rows="2")


@pytest.mark.parametrize("rows", [0, -1, True])
def test_clause_rejects_invalid_row_literals(rows: int | bool) -> None:
    with pytest.raises(DslError, match="positive integer literal"):
        SubqueryCallClause(_returning_title_body(), (), in_transactions=True, of_rows=lit(rows))


@pytest.mark.parametrize("rows", [1.5, "many"])
def test_clause_rejects_non_integer_row_literals(rows: float | str) -> None:
    with pytest.raises(DslError, match="positive integer literal"):
        SubqueryCallClause(_returning_title_body(), (), in_transactions=True, of_rows=lit(rows))


def test_clause_rejects_an_aliased_row_count() -> None:
    with pytest.raises(DslError, match="alias is a projection"):
        SubqueryCallClause(_returning_title_body(), (), in_transactions=True, of_rows=(name("batch") * 2).alias("rows"))


def test_clause_accepts_a_positive_row_literal_and_a_row_parameter() -> None:
    body = _returning_title_body()
    counted = SubqueryCallClause(body, (), in_transactions=True, of_rows=lit(100))
    parameterised = SubqueryCallClause(body, (), in_transactions=True, of_rows=param("rows"))
    counted_children = counted.children()
    parameterised_children = parameterised.children()
    assert len(counted_children) == 2
    assert counted_children[0] is body
    assert counted_children[1] is counted.of_rows
    assert len(parameterised_children) == 2
    assert parameterised_children[0] is body
    assert parameterised_children[1] is parameterised.of_rows


def test_coerce_import_accepts_names_and_variables() -> None:
    assert _coerce_import("p").symbol == SymbolicName("p")
    variable = name("p")
    assert _coerce_import(variable) is variable
    with pytest.raises(DslError, match="variable or a variable name"):
        _coerce_import(42)


RENDERER = Renderer.get(Configuration(server_version="5.26"))


def test_call_with_named_imports_renders_the_scope_clause() -> None:
    body = _returning_title_body()
    statement = match(PERSON).call(body, imports=("p",)).returning(name("title"))
    assert RENDERER.render(statement).cypher == (
        "MATCH (p:Person) CALL (p) { MATCH (m:Movie) RETURN m.title AS title } RETURN title"
    )


def test_call_with_import_all_renders_the_star_form() -> None:
    statement = match(PERSON).call(_returning_title_body(), import_all=True).returning(PERSON, name("title"))
    assert RENDERER.render(statement).cypher == (
        "MATCH (p:Person) CALL (*) { MATCH (m:Movie) RETURN m.title AS title } RETURN p, title"
    )


def test_call_without_imports_renders_the_empty_scope_clause() -> None:
    statement = call(_returning_title_body()).returning(name("title"))
    assert RENDERER.render(statement).cypher == ("CALL () { MATCH (m:Movie) RETURN m.title AS title } RETURN title")


def test_optional_call_renders_the_optional_keyword() -> None:
    statement = (
        match(PERSON).optional_call(_returning_title_body(), imports=("p",)).returning(PERSON["uid"], name("title"))
    )
    assert RENDERER.render(statement).cypher == (
        "MATCH (p:Person) OPTIONAL CALL (p) { MATCH (m:Movie) RETURN m.title AS title } RETURN p.uid, title"
    )


def test_in_transactions_renders_the_modifier_with_and_without_a_row_count() -> None:
    body = create(node("Clone", properties={"uid": name("item")["uid"]})).build()
    batched = (
        unwind(param("rows", [{"uid": "p1"}]), name("item"))
        .call(body, imports=("item",), in_transactions=100)
        .returning(name("item"))
    )
    unbatched = (
        unwind(param("rows", [{"uid": "p1"}]), name("item"))
        .call(body, imports=("item",), in_transactions=True)
        .returning(name("item"))
    )
    assert RENDERER.render(batched).cypher == (
        "UNWIND $rows AS item CALL (item) { CREATE (:Clone {uid: item.uid}) } IN TRANSACTIONS OF 100 ROWS RETURN item"
    )
    assert RENDERER.render(unbatched).cypher == (
        "UNWIND $rows AS item CALL (item) { CREATE (:Clone {uid: item.uid}) } IN TRANSACTIONS RETURN item"
    )


def test_in_transactions_accepts_a_row_count_directly() -> None:
    body = create(node("Clone")).build()
    statement = (
        unwind(fn("range", 1, 100_000), name("item"))
        .call(body, imports=("item",), in_transactions=5_000)
        .returning(name("item"))
    )
    assert RENDERER.render(statement).cypher.endswith("IN TRANSACTIONS OF 5000 ROWS RETURN item")


def test_in_transactions_rejects_invalid_row_literals() -> None:
    body = create(node("Clone")).build()
    with pytest.raises(DslError, match="positive integer literal"):
        unwind(fn("range", 1, 10), name("item")).call(body, imports=("item",), in_transactions=0)
    with pytest.raises(DslError, match="positive integer literal"):
        unwind(fn("range", 1, 10), name("item")).call(body, imports=("item",), in_transactions=lit("many"))


def test_in_transactions_true_renders_the_bare_modifier() -> None:
    body = create(node("Clone")).build()
    statement = (
        unwind(fn("range", 1, 10), name("item"))
        .call(body, imports=("item",), in_transactions=True)
        .returning(name("item"))
    )
    assert RENDERER.render(statement).cypher.endswith("IN TRANSACTIONS RETURN item")


def test_import_names_are_quoted_structurally() -> None:
    body = _returning_title_body()
    reserved = unwind(param("rows", [{"uid": "p1"}]), name("row")).call(body, imports=("row",)).returning(name("title"))
    assert RENDERER.render(reserved).cypher.startswith("UNWIND $rows AS `row` CALL (`row`) {")

    plain = unwind(param("rows", [{"uid": "p1"}]), name("item")).call(body, imports=("item",)).returning(name("title"))
    assert RENDERER.render(plain).cypher.startswith("UNWIND $rows AS item CALL (item) {")

    escaping = Renderer.get(Configuration(server_version="5.26", always_escape_names=True))
    assert escaping.render(plain).cypher.startswith("UNWIND $`rows` AS `item` CALL (`item`) {")


def test_call_accepts_a_builder_for_the_body() -> None:
    body = match(MOVIE).returning(MOVIE["title"].alias("title"))
    statement = match(PERSON).call(body, imports=("p",)).returning(name("title"))
    assert RENDERER.render(statement).cypher == (
        "MATCH (p:Person) CALL (p) { MATCH (m:Movie) RETURN m.title AS title } RETURN title"
    )


def test_call_rejects_an_unfinalisable_body() -> None:
    with pytest.raises(DslError, match="statements, unions and statement builders"):
        match(PERSON).call("db.labels")


def test_call_after_return_is_rejected() -> None:
    with pytest.raises(InvalidClauseOrderError, match="must precede RETURN"):
        match(PERSON).returning(PERSON).call(_returning_title_body(), imports=("p",))


def test_union_body_renders_for_post_union_processing() -> None:
    left = match(PERSON).returning(PERSON["uid"].alias("uid"))
    right = match(MOVIE).returning(MOVIE["uid"].alias("uid"))
    statement = call(union(left, right)).returning(name("uid"))
    assert RENDERER.render(statement).cypher == (
        "CALL () { MATCH (p:Person) RETURN p.uid AS uid UNION MATCH (m:Movie) RETURN m.uid AS uid } RETURN uid"
    )


def test_nested_call_renders() -> None:
    inner = call(_returning_title_body()).returning(name("title")).build()
    statement = match(PERSON).call(inner, imports=("p",)).returning(PERSON, name("title"))
    assert RENDERER.render(statement).cypher == (
        "MATCH (p:Person) CALL (p) { CALL () { MATCH (m:Movie) RETURN m.title AS title } RETURN title } RETURN p, title"
    )


def test_ported_subqueries_it_importing_variables_renders_the_scope_clause() -> None:
    """Port of SubqueriesIT.ResultReturningSubqueries.importingVariablesShouldWork at d3b17e42."""
    body = returning((name("x") * 10).alias("y"))
    statement = unwind([0, 1, 2], name("x")).call(body, imports=("x",)).returning(name("x"), name("y"))
    # Upstream renders "UNWIND [0, 1, 2] AS x CALL {WITH x RETURN (x * 10) AS y} RETURN x, y".
    # This library renders the variable scope clause instead of the importing WITH and adds no
    # parentheses around the multiplication. Neither dialect quotes x or y.
    assert RENDERER.render(statement).cypher == ("UNWIND [0, 1, 2] AS x CALL (x) { RETURN x * 10 AS y } RETURN x, y")


def test_parameters_inside_the_body_are_collected() -> None:
    body = match(MOVIE).where(MOVIE["released"] < param("year", 1999)).returning(MOVIE["title"].alias("title")).build()
    rendered = RENDERER.render(match(PERSON).call(body, imports=("p",)).returning(name("title")))
    assert rendered.cypher == (
        "MATCH (p:Person) CALL (p) { MATCH (m:Movie) WHERE m.released < $year RETURN m.title AS title } RETURN title"
    )
    assert rendered.parameters == {"year": 1999}


def test_imports_must_name_bound_variables_in_the_enclosing_statement() -> None:
    statement = match(PERSON).call(_returning_title_body(), imports=("p", "t")).returning(name("title"))
    with pytest.raises(DslError, match="imports 't', which is not in scope"):
        RENDERER.render(statement)


def test_imports_are_checked_eagerly_after_with() -> None:
    with pytest.raises(DslError, match="which is not in scope"):
        match(PERSON).with_(PERSON).call(_returning_title_body(), imports=("t",))


def test_subquery_cannot_return_an_outer_name() -> None:
    body = returning(lit(1).alias("p")).build()
    with pytest.raises(DslError, match="already holds"):
        match(PERSON).call(body)


@pytest.mark.parametrize("optional", [False, True])
@pytest.mark.parametrize("import_all", [False, True])
@pytest.mark.parametrize(
    ("filtered", "expected"),
    [
        pytest.param(node("Person", name="p"), "(p:Person)", id="omitted-lookup"),
        pytest.param(PERSON.with_labels("Employee"), "(p:Person:Employee)", id="added-label"),
        pytest.param(node("Movie", name="p"), "(p:Movie)", id="different-label"),
        pytest.param(
            node("Person", name="p", properties={"uid": "p2"}), "(p:Person {uid: 'p2'})", id="changed-property"
        ),
    ],
)
def test_imported_match_filters_do_not_redeclare_the_node(
    filtered, expected: str, import_all: bool, optional: bool
) -> None:
    person = node("Person", name="p", properties={"uid": "p1"})
    body = match(filtered).returning(lit(1).alias("one")).build()
    outer = match(person)
    append = outer.optional_call if optional else outer.call
    query = append(body, imports=() if import_all else ("p",), import_all=import_all).returning(name("one"))
    keyword = "OPTIONAL CALL" if optional else "CALL"
    scope = "*" if import_all else "p"
    assert RENDERER.render(query).cypher == (
        f"MATCH (p:Person {{uid: 'p1'}}) {keyword} ({scope}) {{ MATCH {expected} RETURN 1 AS one }} RETURN one"
    )


def test_imported_match_filters_still_check_unimported_property_references() -> None:
    filtered = node("Person", name="p", properties={"uid": name("item")["uid"]})
    body = match(filtered).returning(lit(1).alias("one")).build()
    with pytest.raises(DslError, match="MATCH pattern properties refers to 'item'"):
        unwind([{"uid": "p1"}], name("item")).match(PERSON).call(body, imports=("p",))


def test_import_cannot_be_redeclared_by_with() -> None:
    body = with_(lit("New team").alias("t")).returning(name("t").alias("team")).build()
    with pytest.raises(DslError, match="redeclares imported name 't' in WITH"):
        match(node("Team", name="t")).call(body, imports=("t",))


def test_import_cannot_be_redeclared_by_unwind() -> None:
    body = unwind([1, 2], name("p")).returning(name("p").alias("person")).build()
    with pytest.raises(DslError, match="redeclares imported name 'p'"):
        match(PERSON).call(body, imports=("p",))


def test_unimported_outer_name_is_rejected_inside_the_body() -> None:
    body = match(node("Movie", properties={"title": name("q")["name"]})).returning(lit(1).alias("one")).build()
    with pytest.raises(DslError, match="which is not in scope"):
        match(PERSON, node("Player", name="q")).call(body, imports=("p",))


def test_returning_subquery_cannot_end_a_statement() -> None:
    with pytest.raises(DslError, match="cannot end a statement"):
        match(PERSON).call(_returning_title_body(), imports=("p",)).build()


def test_unit_subquery_can_end_a_statement() -> None:
    body = create(node("Clone")).build()
    assert RENDERER.render(match(PERSON).call(body, imports=("p",))).cypher == (
        "MATCH (p:Person) CALL (p) { CREATE (:Clone) }"
    )


def test_unit_subquery_adds_no_names() -> None:
    body = create(node("Clone", name="clone")).build()
    with pytest.raises(DslError, match="which is not in scope"):
        match(PERSON).with_(PERSON).call(body, imports=("p",)).returning(name("clone"))


def test_names_the_body_does_not_return_stay_unavailable() -> None:
    with pytest.raises(DslError, match="which is not in scope"):
        match(PERSON).with_(PERSON).call(_returning_title_body(), imports=("p",)).returning(name("budget"))


def test_call_does_not_close_the_outer_scope() -> None:
    query = match(PERSON).call(_returning_title_body()).returning(name("uncertified"))
    assert RENDERER.render(query).cypher == (
        "MATCH (p:Person) CALL () { MATCH (m:Movie) RETURN m.title AS title } RETURN uncertified"
    )


def test_a_with_may_pass_an_import_through_unchanged() -> None:
    body = with_(name("p")).remove(PERSON["uid"]).build()
    assert RENDERER.render(match(PERSON).call(body, imports=("p",))).cypher == (
        "MATCH (p:Person) CALL (p) { WITH p REMOVE p.uid }"
    )


def test_a_with_may_alias_an_import_to_itself() -> None:
    body = with_(name("p").alias("p")).returning(name("p")["uid"].alias("uid")).build()
    assert RENDERER.render(match(PERSON).call(body, imports=("p",)).returning(name("uid"))).cypher == (
        "MATCH (p:Person) CALL (p) { WITH p AS p RETURN p.uid AS uid } RETURN uid"
    )


def test_an_inner_with_cannot_read_an_import_it_dropped() -> None:
    with pytest.raises(DslError, match="which is not in scope"):
        with_(name("p")).with_(lit(1).alias("one")).returning(name("p")["uid"].alias("uid")).build()


@pytest.mark.parametrize("reuse_object", [False, True])
def test_correlated_match_may_reuse_an_imported_node_declaration(reuse_object: bool) -> None:
    imported = PERSON if reuse_object else node("Person", name="p")
    body = match(imported.relationship_to(MOVIE, "ACTED_IN")).returning(MOVIE["title"].alias("title")).build()
    query = match(PERSON).call(body, imports=("p",)).returning(name("title"))
    assert RENDERER.render(query).cypher == (
        "MATCH (p:Person) CALL (p) { MATCH (p:Person)-[:ACTED_IN]->(m:Movie) RETURN m.title AS title } RETURN title"
    )


def test_import_all_walks_the_body_with_every_outer_name() -> None:
    body = (
        match(node("Movie", properties={"title": name("q")["name"]}))
        .returning(name("q")["name"].alias("title"))
        .build()
    )
    query = match(node("Team", name="t"), node("Player", name="q")).call(body, import_all=True).returning(name("title"))
    assert RENDERER.render(query).cypher == (
        "MATCH (t:Team), (q:Player) CALL (*) { MATCH (:Movie {title: q.`name`}) RETURN q.`name` AS title } RETURN title"
    )


def test_union_branches_are_each_walked() -> None:
    left = match(MOVIE).returning(MOVIE["title"].alias("title"))
    right = match(node("Movie", properties={"title": name("q")["name"]})).returning(name("q")["name"].alias("title"))
    with pytest.raises(DslError, match="which is not in scope"):
        match(node("Team", name="t"), node("Player", name="q")).call(union(left, right), imports=("t",))


def test_nested_correlated_call_can_be_finalised_before_its_imports_are_known() -> None:
    leaf = returning(name("p")["uid"].alias("uid")).build()
    body = match(MOVIE).call(leaf, imports=("p",)).returning(name("uid")).build()
    query = match(PERSON).call(body, imports=("p",)).returning(name("uid"))
    assert RENDERER.render(query).cypher == (
        "MATCH (p:Person) CALL (p) { MATCH (m:Movie) CALL (p) { RETURN p.uid AS uid } RETURN uid } RETURN uid"
    )


def test_nested_calls_reject_imports_missing_from_the_actual_context() -> None:
    leaf = returning(name("q")["uid"].alias("uid")).build()
    body = call(leaf, imports=("q",)).returning(name("uid")).build()
    with pytest.raises(DslError, match="imports 'q', which is not in scope"):
        match(PERSON).call(body, imports=("p",))


def test_nested_import_all_uses_the_actual_enclosing_imports() -> None:
    leaf = returning(name("p")["uid"].alias("uid")).build()
    body = call(leaf, import_all=True).returning(name("uid")).build()
    query = match(PERSON).call(body, imports=("p",)).returning(name("uid"))
    assert RENDERER.render(query).cypher == (
        "MATCH (p:Person) CALL (p) { CALL (*) { RETURN p.uid AS uid } RETURN uid } RETURN uid"
    )


def test_union_branches_revalidate_nested_correlated_calls() -> None:
    leaf = returning(name("p")["uid"].alias("uid")).build()
    branch = call(leaf, imports=("p",)).returning(name("uid"))
    body = union(returning(name("p")["uid"].alias("uid")), branch)
    assert RENDERER.render(match(PERSON).call(body, imports=("p",)).returning(name("uid"))).cypher == (
        "MATCH (p:Person) CALL (p) { RETURN p.uid AS uid UNION CALL (p) { RETURN p.uid AS uid } RETURN uid } RETURN uid"
    )


@pytest.mark.parametrize("operation", [create, merge])
def test_imported_node_metadata_allows_write_endpoints(operation) -> None:
    body = operation(PERSON.relationship_to(node("Clone"), "COPIED_AS")).build()
    assert RENDERER.render(match(PERSON).call(body, imports=("p",))).cypher == (
        f"MATCH (p:Person) CALL (p) {{ {operation.__name__.upper()} (p)-[:COPIED_AS]->(:Clone) }}"
    )


@pytest.mark.parametrize("operation", [create, merge])
@pytest.mark.parametrize("reference_at_end", [False, True])
def test_imported_write_endpoints_do_not_require_suppressed_lookup_variables(operation, reference_at_end: bool) -> None:
    person = node("Person", name="p", properties={"uid": name("item")["uid"]})
    clone = node("Clone")
    pattern = (
        clone.relationship_to(person, "COPIED_AS") if reference_at_end else person.relationship_to(clone, "COPIED_AS")
    )
    body = operation(pattern).build()
    query = unwind(param("rows", [{"uid": "p1"}]), name("item")).match(person).call(body, imports=("p",))
    endpoints = "(:Clone)-[:COPIED_AS]->(p)" if reference_at_end else "(p)-[:COPIED_AS]->(:Clone)"
    keyword = operation.__name__.upper()
    rendered = RENDERER.render(query)
    assert rendered.cypher == (
        f"UNWIND $rows AS item MATCH (p:Person {{uid: item.uid}}) CALL (p) {{ {keyword} {endpoints} }}"
    )
    assert rendered.parameters == {"rows": [{"uid": "p1"}]}
    assert rendered.unbound_parameters == frozenset()


@pytest.mark.parametrize("operation", [create, merge])
def test_local_write_declarations_still_require_lookup_variables(operation) -> None:
    person = node("Person", name="p", properties={"uid": name("item")["uid"]})
    body = operation(person.relationship_to(node("Clone"), "COPIED_AS")).build()
    with pytest.raises(DslError, match=f"{operation.__name__.upper()} pattern properties refers to 'item'"):
        call(body)


@pytest.mark.parametrize("operation", [create, merge])
@pytest.mark.parametrize("property_owner", ["named-node", "anonymous-node", "relationship"])
def test_imported_write_endpoints_still_check_rendered_property_references(operation, property_owner: str) -> None:
    properties = {"uid": name("item")["uid"]}
    clone = node(
        "Clone",
        name="clone" if property_owner == "named-node" else None,
        properties=properties if property_owner != "relationship" else None,
    )
    pattern = PERSON.relationship_to(
        clone, "COPIED_AS", properties=properties if property_owner == "relationship" else None
    )
    body = operation(pattern).build()
    with pytest.raises(DslError, match=f"{operation.__name__.upper()} pattern properties refers to 'item'"):
        unwind([{"uid": "p1"}], name("item")).match(PERSON).call(body, imports=("p",))


def test_imported_match_filters_may_follow_a_retaining_with() -> None:
    person = node("Person", name="p", properties={"uid": "p1"})
    body = with_(name("p")).match(PERSON.with_labels("Employee")).returning(name("p")["uid"].alias("uid")).build()
    query = match(person).call(body, imports=("p",)).returning(name("uid"))
    assert RENDERER.render(query).cypher == dedent("""\
        MATCH (p:Person {uid: 'p1'}) CALL (p) { WITH p MATCH (p:Person:Employee)
        RETURN p.uid AS uid } RETURN uid""").replace("\n", " ")


@pytest.mark.parametrize("operation", [create, merge])
def test_imported_standalone_nodes_cannot_be_redeclared_by_writes(operation) -> None:
    body = operation(PERSON).build()
    with pytest.raises(DslError, match="redeclares imported name 'p'"):
        match(PERSON).call(body, imports=("p",))


def test_wildcard_exports_are_available_after_a_closed_outer_scope() -> None:
    body = match(MOVIE).returning(asterisk()).build()
    query = match(PERSON).with_(PERSON).call(body).returning(PERSON, MOVIE)
    assert RENDERER.render(query).cypher == ("MATCH (p:Person) WITH p CALL () { MATCH (m:Movie) RETURN * } RETURN p, m")


def test_wildcard_exports_include_imports_for_collision_checks() -> None:
    body = returning(asterisk()).build()
    with pytest.raises(DslError, match="already holds"):
        match(PERSON).call(body, imports=("p",))


def test_raw_exports_leave_the_outer_names_uncertified() -> None:
    body = returning(raw("1 AS one")).build()
    query = with_(lit(1).alias("anchor")).call(body).returning(name("uncertified"))
    assert RENDERER.render(query).cypher == "WITH 1 AS anchor CALL () { RETURN 1 AS one } RETURN uncertified"


@pytest.mark.parametrize("wildcard", [False, True])
def test_exported_node_identities_allow_later_write_endpoints(wildcard: bool) -> None:
    body = match(MOVIE).returning(asterisk() if wildcard else MOVIE.as_expression().alias("film")).build()
    exported = MOVIE if wildcard else node("Movie", name="film")
    query = match(PERSON).with_(PERSON).call(body).create(PERSON.relationship_to(exported, "LIKES"))
    assert RENDERER.render(query).cypher == (
        "MATCH (p:Person) WITH p CALL () { MATCH (m:Movie) RETURN * } CREATE (p)-[:LIKES]->(m)"
        if wildcard
        else "MATCH (p:Person) WITH p CALL () { MATCH (m:Movie) RETURN m AS film } CREATE (p)-[:LIKES]->(film)"
    )


def test_optional_call_factory_renders_without_imports() -> None:
    assert RENDERER.render(optional_call(_returning_title_body()).returning(name("title"))).cypher == (
        "OPTIONAL CALL () { MATCH (m:Movie) RETURN m.title AS title } RETURN title"
    )


@pytest.mark.parametrize("optional", [False, True])
def test_call_after_an_update_needs_with(optional: bool) -> None:
    prefix = match(PERSON).set_(assign(PERSON["uid"], "p1"))
    append = prefix.optional_call if optional else prefix.call
    with pytest.raises(InvalidClauseOrderError, match="needs a WITH boundary"):
        append(create(node("Clone")).build(), imports=("p",))


@pytest.mark.parametrize("optional", [False, True])
def test_with_allows_a_call_after_an_update(optional: bool) -> None:
    prefix = match(PERSON).set_(assign(PERSON["uid"], "p1")).with_(PERSON)
    append = prefix.optional_call if optional else prefix.call
    keyword = "OPTIONAL CALL" if optional else "CALL"
    assert RENDERER.render(append(create(node("Clone")).build(), imports=("p",))).cypher == (
        f"MATCH (p:Person) SET p.uid = 'p1' WITH p {keyword} (p) {{ CREATE (:Clone) }}"
    )


def test_direct_statement_checks_the_update_call_boundary() -> None:
    clauses = match(PERSON).set_(assign(PERSON["uid"], "p1")).clauses
    with pytest.raises(InvalidClauseOrderError, match="needs a WITH boundary"):
        Statement((*clauses, SubqueryCallClause(create(node("Clone")).build())))


def test_nested_unit_calls_can_end_a_statement() -> None:
    body = call(create(node("Clone")).build()).build()
    assert RENDERER.render(call(body)).cypher == "CALL () { CALL () { CREATE (:Clone) } }"


def test_a_nested_call_cannot_rebind_a_discarded_import() -> None:
    leaf = returning(lit(2).alias("p")).build()
    body = with_(lit(1).alias("one")).call(leaf).returning(name("p").alias("person")).build()
    with pytest.raises(DslError, match="redeclares imported name 'p'"):
        match(PERSON).call(body, imports=("p",))


def test_union_wildcard_width_is_rechecked_with_imports() -> None:
    body = union(returning(asterisk()), returning(lit(1).alias("one"), lit(2).alias("two")))
    with pytest.raises(DslError, match="UNION branches project 1 and 2 columns"):
        match(PERSON).call(body, imports=("p",))


def test_imports_can_expand_a_union_wildcard_beyond_its_local_names() -> None:
    first = match(MOVIE).returning(asterisk())
    second = returning(name("p"), lit(1).alias("m"))
    body = union(first, second)
    with pytest.raises(DslError, match="already holds"):
        match(PERSON).call(body, imports=("p",))


def test_imported_node_alias_exports_allow_later_write_endpoints() -> None:
    body = returning(name("p").alias("person")).build()
    query = (
        match(PERSON)
        .call(body, imports=("p",))
        .create(node("Person", name="person").relationship_to(node("Clone"), "COPIED_AS"))
    )
    assert RENDERER.render(query).cypher == (
        "MATCH (p:Person) CALL (p) { RETURN p AS person } CREATE (person)-[:COPIED_AS]->(:Clone)"
    )


@pytest.mark.parametrize("operation", ["create", "merge"])
def test_imported_node_metadata_survives_an_inner_with(operation: str) -> None:
    body = getattr(with_(name("p")), operation)(PERSON.relationship_to(node("Clone"), "COPIED_AS")).build()
    assert RENDERER.render(match(PERSON).call(body, imports=("p",))).cypher == (
        f"MATCH (p:Person) CALL (p) {{ WITH p {operation.upper()} (p)-[:COPIED_AS]->(:Clone) }}"
    )


@pytest.mark.parametrize("operation", ["create", "merge"])
def test_known_scalar_import_is_not_a_write_endpoint(operation: str) -> None:
    body = getattr(with_(name("p")), operation)(PERSON.relationship_to(node("Clone"), "COPIED_AS")).build()
    with pytest.raises(DslError, match="conflicting declaration"):
        unwind([1], name("p")).call(body, imports=("p",))


def test_nested_write_calls_defer_unknown_imported_node_declarations() -> None:
    leaf = create(PERSON.relationship_to(node("Clone"), "COPIED_AS")).build()
    body = call(leaf, imports=("p",)).build()
    assert RENDERER.render(match(PERSON).call(body, imports=("p",))).cypher == (
        "MATCH (p:Person) CALL (p) { CALL (p) { CREATE (p)-[:COPIED_AS]->(:Clone) } }"
    )
    with pytest.raises(DslError, match="redeclares imported name 'p'"):
        match(node("Movie", name="p")).call(body, imports=("p",))


def test_an_initial_wildcard_with_keeps_contextual_imports_for_nested_calls() -> None:
    leaf = returning(name("p")["uid"].alias("uid")).build()
    body = match(MOVIE).with_(asterisk()).call(leaf, imports=("p",)).returning(name("uid")).build()
    query = match(PERSON).call(body, imports=("p",)).returning(name("uid"))
    assert RENDERER.render(query).cypher == (
        "MATCH (p:Person) CALL (p) { MATCH (m:Movie) WITH * CALL (p) { RETURN p.uid AS uid } RETURN uid } RETURN uid"
    )


def test_wildcard_imports_can_pass_unknown_node_metadata_to_a_nested_write_call() -> None:
    leaf = create(PERSON.relationship_to(node("Clone"), "COPIED_AS")).build()
    body = with_(asterisk()).call(leaf, imports=("p",)).build()
    assert RENDERER.render(match(PERSON).call(body, imports=("p",))).cypher == (
        "MATCH (p:Person) CALL (p) { WITH * CALL (p) { CREATE (p)-[:COPIED_AS]->(:Clone) } }"
    )


@pytest.mark.parametrize("operation", ["create", "merge"])
def test_wildcard_imports_after_known_and_raw_projections_defer_write_endpoints(operation: str) -> None:
    person = node("Person", name="p")
    leaf = getattr(with_(name("p")), operation)(person.relationship_to(node("Clone"), "COPIED_AS")).build()
    body = with_(name("p")).with_(raw("p")).call(leaf, import_all=True).returning(lit(1).alias("result")).build()
    query = match(person).call(body, imports=("p",)).returning(name("result"))
    assert RENDERER.render(query).cypher == dedent(f"""\
        MATCH (p:Person) CALL (p) {{ WITH p WITH p
        CALL (*) {{ WITH p {operation.upper()} (p)-[:COPIED_AS]->(:Clone) }}
        RETURN 1 AS result }} RETURN result""").replace("\n", " ")


def test_wildcard_imports_after_known_and_raw_projections_defer_nested_named_write_calls() -> None:
    person = node("Person", name="p")
    leaf = with_(name("p")).create(person.relationship_to(node("Clone"), "COPIED_AS")).build()
    nested = call(leaf, imports=("p",)).build()
    body = with_(name("p")).with_(raw("p")).call(nested, import_all=True).returning(lit(1).alias("result")).build()
    query = match(person).call(body, imports=("p",)).returning(name("result"))
    assert RENDERER.render(query).cypher == dedent("""\
        MATCH (p:Person) CALL (p) { WITH p WITH p
        CALL (*) { CALL (p) { WITH p CREATE (p)-[:COPIED_AS]->(:Clone) } }
        RETURN 1 AS result } RETURN result""").replace("\n", " ")


def test_wildcard_imports_can_be_aliased_before_writing() -> None:
    alias = node("Person", name="person")
    body = (
        with_(asterisk())
        .with_(name("p").alias("person"))
        .create(alias.relationship_to(node("Clone"), "COPIED_AS"))
        .build()
    )
    assert RENDERER.render(match(PERSON).call(body, imports=("p",))).cypher == (
        "MATCH (p:Person) CALL (p) { WITH * WITH p AS person CREATE (person)-[:COPIED_AS]->(:Clone) }"
    )


@pytest.mark.parametrize("import_all", [False, True])
def test_a_match_cannot_rebind_a_discarded_import(import_all: bool) -> None:
    body = with_(lit(1).alias("one")).match(PERSON).returning(PERSON["uid"].alias("uid")).build()
    with pytest.raises(DslError, match="redeclares imported name 'p'"):
        query = match(PERSON).call(body, imports=() if import_all else ("p",), import_all=import_all)
        RENDERER.render(query.returning(name("uid")))


@pytest.mark.parametrize("import_all", [False, True])
def test_a_match_cannot_rebind_a_discarded_relationship_import(import_all: bool) -> None:
    outer = PERSON.relationship_to(MOVIE, "ACTED_IN", name="r")
    reused = node("Person").relationship_to(node("Movie"), "ACTED_IN", name="r")
    body = with_(lit(1).alias("one")).match(reused).returning(lit(1).alias("answer")).build()
    with pytest.raises(DslError, match="redeclares imported name 'r'"):
        query = match(outer).call(body, imports=() if import_all else ("r",), import_all=import_all)
        RENDERER.render(query.returning(name("answer")))


@pytest.mark.parametrize("import_all", [False, True])
def test_a_match_can_reference_a_relationship_import_kept_by_with(import_all: bool) -> None:
    outer = PERSON.relationship_to(MOVIE, "ACTED_IN", name="r")
    reused = node("Person").relationship_to(node("Movie"), "ACTED_IN", name="r")
    body = with_(name("r")).match(reused).returning(lit(1).alias("answer")).build()
    query = match(outer).call(body, imports=() if import_all else ("r",), import_all=import_all)
    scope = "*" if import_all else "r"
    assert RENDERER.render(query.returning(name("answer"))).cypher == (
        f"MATCH (p:Person)-[r:ACTED_IN]->(m:Movie) CALL ({scope}) "
        "{ WITH r MATCH (:Person)-[r:ACTED_IN]->(:Movie) RETURN 1 AS answer } RETURN answer"
    )


def test_union_exports_common_node_declarations_for_later_write_endpoints() -> None:
    other = node("Movie", name="other")
    body = union(
        match(MOVIE).returning(MOVIE.as_expression().alias("film")),
        match(other).returning(other.as_expression().alias("film")),
    )
    query = match(PERSON).call(body).create(PERSON.relationship_to(node("Movie", name="film"), "LIKES"))
    assert RENDERER.render(query).cypher == (
        "MATCH (p:Person) CALL () { MATCH (m:Movie) RETURN m AS film "
        "UNION MATCH (other:Movie) RETURN other AS film } CREATE (p)-[:LIKES]->(film)"
    )


def test_union_exports_do_not_certify_conflicting_node_declarations() -> None:
    other = node("Person", name="other")
    body = union(
        match(MOVIE).returning(MOVIE.as_expression().alias("film")),
        match(other).returning(other.as_expression().alias("film")),
    )
    with pytest.raises(DslError, match="conflicting declaration"):
        match(PERSON).call(body).create(PERSON.relationship_to(node("Movie", name="film"), "LIKES"))


def test_every_call_records_the_scope_clauses_requirement() -> None:
    statement = match(PERSON).call(_returning_title_body(), imports=("p",)).returning(name("title")).build()
    assert [(requirement.capability, requirement.path) for requirement in analyse(statement).requirements] == [
        (Capability.SCOPE_CLAUSES, (1,))
    ]


def test_optional_call_and_in_transactions_record_their_requirements() -> None:
    statement = (
        unwind(param("rows", [{"uid": "p1"}]), name("item"))
        .optional_call(create(node("Clone")).build(), imports=("item",), in_transactions=100)
        .returning(name("item"))
        .build()
    )
    assert [(requirement.capability, requirement.path) for requirement in analyse(statement).requirements] == [
        (Capability.SCOPE_CLAUSES, (1,)),
        (Capability.OPTIONAL_CALL, (1,)),
        (Capability.IN_TRANSACTIONS, (1,)),
    ]


@pytest.mark.parametrize("language", [Language.AUTO, Language.NONE, Language.CYPHER_5, Language.CYPHER_25])
def test_call_subqueries_have_no_language_floor(language: Language) -> None:
    renderer = Renderer.get(Configuration(server_version="2026.10", language=language))
    statement = optional_call(create(node("Clone")).build(), in_transactions=100)
    prefix = {Language.CYPHER_5: "CYPHER 5 ", Language.CYPHER_25: "CYPHER 25 "}.get(language, "")
    assert (
        renderer.render(statement).cypher
        == f"{prefix}OPTIONAL CALL () {{ CREATE (:Clone) }} IN TRANSACTIONS OF 100 ROWS"
    )


def test_pinned_cypher_5_accepts_call_subqueries_on_the_minimum_supported_release() -> None:
    pinned = Renderer.get(Configuration(server_version="5.26", language=Language.CYPHER_5))
    statement = match(PERSON).call(_returning_title_body(), imports=("p",)).returning(name("title"))
    assert pinned.render(statement).cypher == (
        "CYPHER 5 MATCH (p:Person) CALL (p) { MATCH (m:Movie) RETURN m.title AS title } RETURN title"
    )


@pytest.mark.parametrize("operation", [create, merge])
def test_reused_body_renders_imported_and_local_write_endpoints_independently(operation) -> None:
    person = node("Person", name="p", properties={"uid": param("uid", "p1")})
    clone = node("Clone", name="clone", properties={"uid": lit("copy")})
    body = operation(person.relationship_to(clone, "COPIED_AS")).build()
    query = match(person).call(body, imports=("p",)).call(body)
    keyword = operation.__name__.upper()
    expected = dedent(f"""\
        MATCH (p:Person {{uid: $uid}})
        CALL (p) {{ {keyword} (p)-[:COPIED_AS]->(clone:Clone {{uid: 'copy'}}) }}
        CALL () {{ {keyword} (p:Person {{uid: $uid}})-[:COPIED_AS]->(clone:Clone {{uid: 'copy'}}) }}""").replace(
        "\n", " "
    )
    assert RENDERER.render(query).cypher == expected
    assert RENDERER.render(call(body)).cypher == (
        f"CALL () {{ {keyword} (p:Person {{uid: $uid}})-[:COPIED_AS]->(clone:Clone {{uid: 'copy'}}) }}"
    )
    assert RENDERER.render(query).cypher == expected


@pytest.mark.parametrize("operation", [create, merge])
@pytest.mark.parametrize("import_all", [False, True])
def test_union_write_branches_each_start_with_the_calls_imported_node_metadata(operation, import_all: bool) -> None:
    clone = node("Clone", name="clone")
    branch = operation(PERSON.relationship_to(clone, "COPIED_AS")).returning(lit(1).alias("one")).build()
    query = (
        match(PERSON)
        .with_(asterisk())
        .call(union(branch, branch), imports=() if import_all else ("p",), import_all=import_all)
        .returning(name("one"))
    )
    scope = "*" if import_all else "p"
    keyword = operation.__name__.upper()
    assert RENDERER.render(query).cypher == dedent(f"""\
        MATCH (p:Person) WITH * CALL ({scope}) {{
        {keyword} (p)-[:COPIED_AS]->(clone:Clone) RETURN 1 AS one
        UNION {keyword} (p)-[:COPIED_AS]->(clone:Clone) RETURN 1 AS one }} RETURN one""").replace("\n", " ")


@pytest.mark.parametrize("import_all", [False, True])
def test_nested_write_calls_keep_imported_node_metadata(import_all: bool) -> None:
    leaf = merge(PERSON.relationship_to(node("Clone", name="clone"), "COPIED_AS")).build()
    body = with_(asterisk()).call(leaf, imports=() if import_all else ("p",), import_all=import_all).build()
    query = match(PERSON).call(body, import_all=True)
    scope = "*" if import_all else "p"
    assert RENDERER.render(query).cypher == (
        f"MATCH (p:Person) CALL (*) {{ WITH * CALL ({scope}) {{ MERGE (p)-[:COPIED_AS]->(clone:Clone) }} }}"
    )


def test_nested_body_and_row_count_parameters_are_query_global_and_fresh() -> None:
    leaf = create(
        node("Clone", properties={"payload": param("payload", {"ids": [1]}), "shared": param("shared")})
    ).build()
    body = call(leaf).build()
    query = (
        unwind(param("items", [1]), name("item"))
        .call(body, in_transactions=param("batchRows", 100))
        .returning(param("shared", [2]), param("unbound"))
        .build()
    )
    assert [parameter.symbol.value for parameter in analyse(query).parameters] == [
        "items",
        "payload",
        "shared",
        "batchRows",
        "shared",
        "unbound",
    ]
    first = RENDERER.render(query)
    assert first.cypher == dedent("""\
        UNWIND $items AS item CALL () {
        CALL () { CREATE (:Clone {payload: $payload, shared: $shared}) }
        } IN TRANSACTIONS OF $batchRows ROWS RETURN $shared, $unbound""").replace("\n", " ")
    expected = {"items": [1], "payload": {"ids": [1]}, "shared": [2], "batchRows": 100}
    assert first.parameters == expected
    assert first.unbound_parameters == frozenset({"unbound"})
    first.parameters["payload"]["ids"].append(9)
    first.parameters["items"].append(9)
    second = RENDERER.render(query)
    assert second.parameters == expected
    assert second.parameters is not first.parameters
    assert second.unbound_parameters == frozenset({"unbound"})
    assert second.unbound_parameters is not first.unbound_parameters


@pytest.mark.parametrize(("body_value", "first_rows", "second_rows"), [(1, 2, 1), (1, 1, 2), (2, 1, 1)])
def test_nested_body_and_row_count_parameter_conflicts_are_query_global(
    body_value: int, first_rows: int, second_rows: int
) -> None:
    leaf = create(node("Clone", properties={"uid": param("batch", body_value)})).build()
    body = call(leaf).build()
    query = call(body, in_transactions=param("batch", first_rows)).call(
        body, in_transactions=param("batch", second_rows)
    )
    with pytest.raises(ConflictingParameterError):
        RENDERER.render(query)


def test_procedure_call_holds_its_parts() -> None:
    clause = ProcedureCallClause(LABELS, (), optional=False)
    assert clause.name == LABELS
    assert clause.arguments == ()
    assert clause.optional is False
    assert clause.yields == ()
    assert clause.predicate is None
    assert clause.children() == ()


def test_procedure_call_accepts_arguments() -> None:
    first_argument = lit("Person")
    second_argument = param("limit", 10)
    clause = ProcedureCallClause(LABELS, (first_argument, second_argument), optional=False)
    assert clause.arguments == (first_argument, second_argument)
    assert clause.children() == (first_argument, second_argument)


def test_procedure_call_accepts_the_optional_flag() -> None:
    assert ProcedureCallClause(LABELS, (), optional=True).optional is True


def test_procedure_call_accepts_plain_and_aliased_yields() -> None:
    label = name("label")
    aliased = name("label").alias("name")
    clause = ProcedureCallClause(LABELS, (), optional=False, yields=(label, aliased))
    assert clause.yields == (label, aliased)


def test_procedure_call_accepts_a_predicate_over_yields() -> None:
    label = name("label")
    predicate = label == lit("Person")
    clause = ProcedureCallClause(LABELS, (), optional=False, yields=(label,), predicate=predicate)
    assert clause.predicate is predicate
    assert clause.children() == (label, predicate)


@pytest.mark.parametrize(
    ("invalid_name", "message"),
    [
        pytest.param(["db", "labels"], "tuple of string segments", id="list"),
        pytest.param("db.labels", "tuple of string segments", id="string"),
        pytest.param(("db", 7), "tuple of string segments", id="non-string-segment"),
        pytest.param((), "at least one segment", id="empty"),
    ],
)
def test_procedure_call_rejects_a_name_it_cannot_render(invalid_name: object, message: str) -> None:
    with pytest.raises(DslError, match=message):
        ProcedureCallClause(invalid_name, (), optional=False)


def test_procedure_call_rejects_a_name_segment_that_is_not_an_identifier() -> None:
    with pytest.raises(InvalidIdentifierError, match="cannot be empty"):
        ProcedureCallClause(("db", ""), (), optional=False)


@pytest.mark.parametrize("optional", ["yes", 1, None])
def test_procedure_call_rejects_a_boolean_flag_of_the_wrong_type(optional: object) -> None:
    with pytest.raises(DslError, match="boolean choice"):
        ProcedureCallClause(LABELS, (), optional=optional)


def test_procedure_call_requires_tuple_arguments() -> None:
    with pytest.raises(DslError, match="must be a tuple"):
        ProcedureCallClause(LABELS, [lit("Person")], optional=False)


def test_procedure_call_requires_tuple_yields() -> None:
    with pytest.raises(DslError, match="must be a tuple"):
        ProcedureCallClause(LABELS, (), optional=False, yields=[name("label")])


@pytest.mark.parametrize("argument", ["Person", 42])
def test_procedure_call_rejects_arguments_that_are_not_expressions(argument: object) -> None:
    with pytest.raises(DslError, match="arguments need expressions"):
        ProcedureCallClause(LABELS, (argument,), optional=False)


def test_procedure_call_rejects_an_aliased_argument() -> None:
    with pytest.raises(DslError, match="alias is a projection"):
        ProcedureCallClause(LABELS, (name("label").alias("name"),), optional=False)


@pytest.mark.parametrize(
    ("item", "message"),
    [
        pytest.param(lit("label"), "takes a variable or an aliased variable", id="literal"),
        pytest.param(name("label")["name"].alias("name"), "aliases a variable", id="alias-over-property"),
    ],
)
def test_procedure_call_rejects_yield_items_that_bind_no_variable(item: object, message: str) -> None:
    with pytest.raises(DslError, match=message):
        ProcedureCallClause(LABELS, (), optional=False, yields=(item,))


@pytest.mark.parametrize(
    "items",
    [
        pytest.param((name("label"), name("label")), id="two-plain"),
        pytest.param((name("label"), name("other").alias("label")), id="aliased-and-plain"),
    ],
)
def test_procedure_call_rejects_duplicate_yield_bindings(items: object) -> None:
    with pytest.raises(DslError, match="already binds 'label'"):
        ProcedureCallClause(LABELS, (), optional=False, yields=items)


def test_procedure_call_rejects_a_predicate_without_yields() -> None:
    with pytest.raises(DslError, match="filters YIELD output"):
        ProcedureCallClause(LABELS, (), optional=False, predicate=name("label") == lit("Person"))


def test_procedure_call_rejects_a_predicate_that_is_not_an_expression() -> None:
    with pytest.raises(DslError, match="predicate needs an expression"):
        ProcedureCallClause(LABELS, (), optional=False, yields=(name("label"),), predicate="label = 'Person'")


def test_procedure_call_rejects_an_aliased_predicate() -> None:
    predicate = (name("label") == lit("Person")).alias("matches")
    with pytest.raises(DslError, match="alias is a projection"):
        ProcedureCallClause(LABELS, (), optional=False, yields=(name("label"),), predicate=predicate)


def test_procedure_call_children_follow_rendered_order() -> None:
    first_argument = lit("db")
    second_argument = lit("labels")
    first_yield = name("label")
    second_yield = name("other").alias("name")
    predicate = name("label") == lit("Person")
    clause = ProcedureCallClause(
        LABELS,
        (first_argument, second_argument),
        optional=False,
        yields=(first_yield, second_yield),
        predicate=predicate,
    )
    assert clause.children() == (first_argument, second_argument, first_yield, second_yield, predicate)


# The builder surface: construction, coercion, clause order and finalisation.


def test_call_procedure_starts_a_builder_with_the_call_clause() -> None:
    builder = call_procedure("db.labels")
    assert len(builder.clauses) == 1
    clause = builder.clauses[0]
    assert isinstance(clause, ProcedureCallClause)
    assert clause.name == LABELS
    assert clause.arguments == ()
    assert clause.optional is False
    assert clause.yields == ()
    assert clause.predicate is None


def test_optional_call_procedure_sets_the_optional_flag() -> None:
    clause = optional_call_procedure("db.labels").clauses[0]
    assert isinstance(clause, ProcedureCallClause)
    assert clause.name == LABELS
    assert clause.optional is True


def test_call_procedure_coerces_argument_inputs() -> None:
    passed = name("p")
    clause = call_procedure("db.labels", "Person", 10, passed).clauses[0]
    assert isinstance(clause, ProcedureCallClause)
    first, second, third = clause.arguments
    assert isinstance(first, Literal) and first.value == "Person"
    assert isinstance(second, Literal) and second.value == 10
    assert third is passed


def test_call_procedure_rejects_an_aliased_argument() -> None:
    with pytest.raises(DslError, match="alias is a projection"):
        call_procedure("db.labels", name("label").alias("name"))


def test_yielding_coerces_and_appends_items() -> None:
    label = name("label")
    clause = call_procedure("db.labels").yielding("propertyKey", label, name("other").alias("name")).clauses[0]
    assert isinstance(clause, ProcedureCallClause)
    plain, variable, aliased = clause.yields
    assert isinstance(plain, Variable) and plain.symbol.value == "propertyKey"
    assert variable is label
    assert isinstance(aliased, AliasedExpression) and aliased.alias_name.value == "name"
    builder = call_procedure("db.labels").yielding("label")
    appended = builder.yielding(name("other").alias("name")).clauses[0].yields
    assert len(appended) == 2
    assert appended[0] is builder.clauses[0].yields[0]


def test_yielding_requires_a_procedure_call_owner() -> None:
    with pytest.raises(InvalidClauseOrderError, match="must immediately follow the procedure call"):
        match(PERSON).yielding("label")
    with pytest.raises(InvalidClauseOrderError, match="must immediately follow the procedure call"):
        with_(PERSON).yielding("label")


def test_yielding_requires_at_least_one_item() -> None:
    with pytest.raises(DslError, match="at least one item"):
        call_procedure("db.labels").yielding()


def test_where_attaches_to_a_yielded_call_and_combines() -> None:
    first = name("label") == lit("Person")
    builder = call_procedure("db.labels").yielding("label").where(first)
    clause = builder.clauses[0]
    assert isinstance(clause, ProcedureCallClause)
    assert clause.predicate is first
    combined = builder.where(name("label") != lit("Movie")).clauses[0].predicate
    assert isinstance(combined, BinaryOperation)


def test_where_on_a_yield_less_call_is_rejected() -> None:
    with pytest.raises(DslError, match="filters YIELD output"):
        call_procedure("db.labels").where(name("label") == lit("Person"))


@pytest.mark.parametrize("optional", [False, True])
def test_procedure_call_after_an_update_needs_with(optional: bool) -> None:
    prefix = match(PERSON).set_(assign(PERSON["uid"], "p1"))
    append = prefix.optional_call_procedure if optional else prefix.call_procedure
    with pytest.raises(InvalidClauseOrderError, match="needs a WITH boundary"):
        append("db.labels")


@pytest.mark.parametrize("optional", [False, True])
def test_with_allows_a_procedure_call_after_an_update(optional: bool) -> None:
    prefix = match(PERSON).set_(assign(PERSON["uid"], "p1")).with_(PERSON)
    append = prefix.optional_call_procedure if optional else prefix.call_procedure
    clause = append("db.labels").clauses[-1]
    assert isinstance(clause, ProcedureCallClause)
    assert clause.optional is optional


def test_procedure_call_after_return_is_rejected() -> None:
    with pytest.raises(InvalidClauseOrderError, match="must precede RETURN"):
        match(PERSON).returning(PERSON).call_procedure("db.labels")


def test_a_yield_less_procedure_call_can_end_a_statement() -> None:
    assert isinstance(call_procedure("db.labels").build(), Statement)


def test_a_yield_less_procedure_call_can_end_a_larger_query() -> None:
    assert isinstance(match(PERSON).with_(name("p")).call_procedure("db.labels").build(), Statement)


def test_a_yielded_procedure_call_cannot_end_a_statement() -> None:
    with pytest.raises(DslError, match="cannot end a statement"):
        call_procedure("db.labels").yielding("label").build()


# The scope rules: yielded bindings, reference checks and capability recording.


def test_yielded_names_reach_a_following_return() -> None:
    builder = with_(lit(1).alias("one")).call_procedure("db.labels").yielding("label")
    assert isinstance(builder.returning(name("label")).build(), Statement)
    with pytest.raises(DslError, match="not in scope"):
        builder.returning(name("ghost"))


def test_aliased_yields_bind_the_alias_not_the_column() -> None:
    builder = with_(lit(1).alias("one")).call_procedure("db.propertyKeys").yielding(name("propertyKey").alias("prop"))
    assert isinstance(builder.returning(name("prop")).build(), Statement)
    with pytest.raises(DslError, match="not in scope"):
        builder.returning(name("propertyKey"))


def test_a_yielded_name_the_outer_query_holds_is_rejected() -> None:
    with pytest.raises(DslError, match="which the outer query already holds"):
        with_(lit(1).alias("label")).call_procedure("db.labels").yielding("label")


def test_a_yielded_name_an_import_holds_is_rejected() -> None:
    leaf = returning(lit(1).alias("one")).build()
    body = call(leaf, imports=("p",)).call_procedure("db.labels").yielding("p").returning(name("one")).build()
    with pytest.raises(DslError, match="redeclares imported name 'p'"):
        match(PERSON).call(body, imports=("p",))


def test_procedure_arguments_are_checked_against_the_incoming_scope() -> None:
    with pytest.raises(DslError, match="not in scope"):
        with_(lit(1).alias("one")).call_procedure("db.labels", name("missing"))


def test_the_call_predicate_sees_outer_and_yielded_names() -> None:
    builder = with_(lit(1).alias("one")).call_procedure("db.labels").yielding("label")
    query = builder.where(name("one") == name("label")).returning(name("label")).build()
    assert isinstance(query, Statement)
    with pytest.raises(DslError, match="not in scope"):
        builder.where(name("ghost") == lit(1))


def test_a_yield_less_call_leaves_the_scope_untouched() -> None:
    builder = with_(lit(1).alias("one")).call_procedure("db.labels")
    assert isinstance(builder.returning(name("one")).build(), Statement)
    with pytest.raises(DslError, match="not in scope"):
        builder.returning(name("label"))


def test_optional_procedure_call_records_its_capability() -> None:
    statement = optional_call_procedure("db.labels").build()
    assert [(requirement.capability, requirement.path) for requirement in analyse(statement).requirements] == [
        (Capability.OPTIONAL_CALL, (0,))
    ]


def test_a_plain_procedure_call_records_no_capability() -> None:
    assert analyse(call_procedure("db.labels").build()).requirements == ()


# Rendering the procedure call.


def test_procedure_call_without_arguments_renders_the_empty_parentheses() -> None:
    assert RENDERER.render(call_procedure("db.labels")).cypher == "CALL db.labels()"


def test_procedure_call_renders_its_arguments_in_order() -> None:
    statement = optional_call_procedure("apoc.neighbors.tohop", param("p"), "KNOWS>", 1)
    assert RENDERER.render(statement).cypher == "OPTIONAL CALL apoc.neighbors.tohop($p, 'KNOWS>', 1)"


def test_procedure_call_keeps_unbound_arguments_unbound() -> None:
    rendered = RENDERER.render(optional_call_procedure("apoc.neighbors.tohop", param("p"), "KNOWS>", 1))
    assert rendered.parameters == {}
    assert rendered.unbound_parameters == frozenset({"p"})


def test_procedure_call_renders_a_yield_item_under_an_alias() -> None:
    statement = call_procedure("db.propertyKeys").yielding(name("propertyKey").alias("prop")).returning(name("prop"))
    assert RENDERER.render(statement).cypher == "CALL db.propertyKeys() YIELD propertyKey AS prop RETURN prop"


def test_procedure_call_renders_plain_and_aliased_yields_in_one_list() -> None:
    statement = (
        call_procedure("db.propertyKeys")
        .yielding("propertyKey", name("prop").alias("other"))
        .returning(name("propertyKey"), name("other"))
    )
    assert RENDERER.render(statement).cypher == (
        "CALL db.propertyKeys() YIELD propertyKey, prop AS other RETURN propertyKey, other"
    )


def test_procedure_call_renders_its_filter_after_the_yields() -> None:
    statement = (
        call_procedure("dbms.checkConfigValue", param("setting"), "true")
        .yielding(name("valid").alias("ok"))
        .where(name("ok") == lit(True))
        .returning(name("ok"))
    )
    assert RENDERER.render(statement).cypher == (
        "CALL dbms.checkConfigValue($setting, 'true') YIELD valid AS ok WHERE ok = true RETURN ok"
    )


def test_procedure_name_segments_and_yields_are_quoted_structurally() -> None:
    statement = call_procedure("db.my-labels").yielding(name("row")).returning(name("row"))
    assert RENDERER.render(statement).cypher == "CALL db.`my-labels`() YIELD `row` RETURN `row`"


def test_procedure_names_follow_the_function_name_rule_under_forced_escaping() -> None:
    escaping = Renderer.get(Configuration(server_version="5.26", always_escape_names=True))
    statement = call_procedure("db.labels").yielding(name("label")).returning(name("label"))
    assert escaping.render(statement).cypher == "CALL db.labels() YIELD `label` RETURN `label`"


def test_ported_procedure_calls_it_yield_items_renamed() -> None:
    """Port of ProcedureCallsIT.yieldItemsRenamed at d3b17e42."""
    statement = call_procedure("db.propertyKeys").yielding(name("propertyKey").alias("prop")).returning(name("prop"))
    # Upstream renders "CALL db.propertyKeys() YIELD propertyKey AS prop" and lets the yielded
    # call end the statement. This library requires the yielded names to feed a following
    # clause, so the scenario returns the aliased item.
    assert RENDERER.render(statement).cypher == "CALL db.propertyKeys() YIELD propertyKey AS prop RETURN prop"


def test_ported_procedure_calls_it_where() -> None:
    """Port of ProcedureCallsIT.where at d3b17e42."""
    statement = (
        call_procedure("dbms.listConfig", "browser")
        .yielding("name")
        .where(name("name") == lit("browser.allowlist"))
        .returning(asterisk())
    )
    # Upstream filters with the regex operator "=~", which this library does not model. The
    # scenario keeps the argument, the yield, the filter position and the asterisk return.
    # "name" is a reserved word here, so the renderer quotes it; upstream does not.
    assert RENDERER.render(statement).cypher == (
        "CALL dbms.listConfig('browser') YIELD `name` WHERE `name` = 'browser.allowlist' RETURN *"
    )


def test_ported_procedure_calls_it_with_then_returning_in_query() -> None:
    """Port of ProcedureCallsIT.withThanReturningInQuery at d3b17e42."""
    label = name("label")
    statement = (
        match(node("Person", name="n"))
        .with_(name("n"))
        .call_procedure("db.labels")
        .yielding(label)
        .with_(label)
        .returning(count(label).alias("numLabels"))
    )
    # Upstream matches an unlabelled node, which this library's node grammar does not express,
    # so the scenario matches a labelled one. "label" is a reserved word here, so the renderer
    # quotes it; upstream does not.
    assert RENDERER.render(statement).cypher == (
        "MATCH (n:Person) WITH n CALL db.labels() YIELD `label` WITH `label` RETURN count(`label`) AS numLabels"
    )

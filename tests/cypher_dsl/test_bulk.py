# Ported from the Java Cypher-DSL test suite (neo4j/cypher-dsl, Apache-2.0).
# Traced source: CypherIT. Rewritten for pytest.
"""
Parameterised bulk operations driven by one rows parameter.

One query with one rows parameter performs a bulk create, merge or map update. The
library supplies the syntax and the binding snapshot; it never loops over the rows or
decides how they should be executed.

Identifier quoting is conservative here. ``row`` is a reserved word, so the fixtures
below show it quoted rather than the bare form used in illustrative plan output.
"""

from __future__ import annotations

import pytest

from cypher_dsl import (
    Configuration,
    CreateClause,
    Renderer,
    ReturnClause,
    Statement,
    SymbolicName,
    UnwindClause,
    Variable,
    assign,
    create,
    lit,
    map_,
    match,
    name,
    node,
    param,
    returning,
    union,
    unwind,
    update_properties,
)
from cypher_dsl.errors import DslError, InvalidClauseOrderError, InvalidIdentifierError


def _render(value):
    return Renderer.get(Configuration(server_version="5.26")).render(value)


def test_bulk_create_uses_one_rows_parameter():
    rows = [{"uid": "p1", "name": "Ada"}, {"uid": "p2", "name": "Grace"}]
    row = name("row")
    person = node("Person", name="p", properties={"uid": row["uid"], "name": row["name"]})
    query = unwind(param("rows", rows), row).create(person).returning(person["uid"])
    rows[0]["name"] = "Changed"
    rendered = _render(query)
    assert rendered.cypher == (
        "UNWIND $rows AS `row` CREATE (p:Person {uid: `row`.uid, `name`: `row`.`name`}) RETURN p.uid"
    )
    assert rendered.parameters["rows"][0]["name"] == "Ada"


def test_where_cannot_attach_directly_to_unwind():
    row = name("row")
    with pytest.raises(InvalidClauseOrderError):
        unwind(param("rows"), row).where(row["uid"] == "p1")


def test_unwind_requires_a_variable_target():
    with pytest.raises(DslError, match="variable"):
        unwind(param("rows"), "row")
    with pytest.raises(DslError, match="variable"):
        unwind(param("rows"), lit("row"))


def test_unwind_accepts_an_inline_literal_list():
    row = name("row")
    assert _render(unwind([1, True, False], row).returning(row)).cypher == (
        "UNWIND [1, true, false] AS `row` RETURN `row`"
    )


def test_bulk_create_reads_a_row_map_expression():
    row = name("row")
    person = node("Person", name="p", properties=map_({"uid": row["uid"]}))
    query = unwind(param("rows", [{"uid": "p1"}]), row).create(person).returning(person)
    assert _render(query).cypher == "UNWIND $rows AS `row` CREATE (p:Person {uid: `row`.uid}) RETURN p"


def test_bulk_merge_uses_the_row_as_identity_and_updates_other_properties():
    rows = [{"uid": "p1", "given": "Ada"}]
    row = name("row")
    person = node("Person", name="p", properties={"uid": row["uid"]})
    query = (
        unwind(param("rows", rows), row)
        .merge(person)
        .on_create(assign(person["given"], row["given"]))
        .on_match(assign(person["given"], row["given"]))
        .returning(person["uid"])
    )
    assert _render(query).cypher == (
        "UNWIND $rows AS `row` MERGE (p:Person {uid: `row`.uid}) "
        "ON CREATE SET p.given = `row`.given ON MATCH SET p.given = `row`.given RETURN p.uid"
    )


def test_a_reusable_identity_map_works_for_a_bulk_merge():
    row = name("row")
    person = node("Person", name="p", properties=map_({"uid": row["uid"]}))
    query = (
        unwind(param("rows", [{"uid": "p1", "given": "Ada"}]), row)
        .merge(person)
        .on_create(assign(person["given"], row["given"]))
        .returning(person)
    )
    assert _render(query).cypher == (
        "UNWIND $rows AS `row` MERGE (p:Person {uid: `row`.uid}) ON CREATE SET p.given = `row`.given RETURN p"
    )


def test_a_whole_map_replacement_uses_one_rows_parameter():
    rows = [{"uid": "p1", "given": "Ada"}]
    row = name("row")
    person = node("Person", name="p")
    query = unwind(param("rows", rows), row).match(person).set_(assign(person, row)).returning(person)
    assert _render(query).cypher == "UNWIND $rows AS `row` MATCH (p:Person) SET p = `row` RETURN p"


def test_a_partial_map_patch_uses_the_same_rows_parameter():
    rows = [{"uid": "p1", "given": "Ada"}]
    row = name("row")
    person = node("Person", name="p")
    query = unwind(param("rows", rows), row).match(person).set_(update_properties(person, row)).returning(person)
    assert _render(query).cypher == "UNWIND $rows AS `row` MATCH (p:Person) SET p += `row` RETURN p"


def test_filtering_after_unwind_needs_a_with_boundary():
    row = name("row")
    query = unwind(param("rows"), row).with_(row).where(row["uid"] == "p1").returning(row["uid"])
    assert _render(query).cypher == "UNWIND $rows AS `row` WITH `row` WHERE `row`.uid = 'p1' RETURN `row`.uid"


def test_unwind_values_are_checked_against_a_closed_scope():
    person = node("Person", name="p")
    other = node("Person", name="q")
    with pytest.raises(DslError, match="not in scope"):
        match(person, other).with_(person).unwind(other["uid"], name("row"))


def test_one_bound_rows_parameter_can_be_reused_in_several_occurrences():
    rows = [{"uid": "p1"}]
    row = name("row")
    item = name("item")
    query = unwind(param("rows", rows), row).with_(row).unwind(param("rows"), item).returning(item)
    rendered = _render(query)
    assert rendered.cypher == "UNWIND $rows AS `row` WITH `row` UNWIND $rows AS item RETURN item"
    assert rendered.parameters == {"rows": [{"uid": "p1"}]}
    assert rendered.unbound_parameters == frozenset()


def test_an_empty_rows_parameter_still_renders_one_clause():
    row = name("row")
    rendered = _render(unwind(param("rows", []), row).returning(row["uid"]))
    assert rendered.cypher == "UNWIND $rows AS `row` RETURN `row`.uid"
    assert rendered.parameters == {"rows": []}


def test_mutating_a_returned_parameter_cannot_change_a_second_render():
    rows = [{"uid": "p1", "name": "Ada"}]
    row = name("row")
    person = node("Person", name="p", properties={"uid": row["uid"], "name": row["name"]})
    query = unwind(param("rows", rows), row).create(person).returning(person["uid"])
    renderer = Renderer.get(Configuration(server_version="5.26"))
    first = renderer.render(query)
    first.parameters["rows"][0]["uid"] = "changed"
    second = renderer.render(query)
    assert second.parameters["rows"] == [{"uid": "p1", "name": "Ada"}]
    assert second.cypher == (
        "UNWIND $rows AS `row` CREATE (p:Person {uid: `row`.uid, `name`: `row`.`name`}) RETURN p.uid"
    )


def test_unwind_cannot_follow_return_and_a_read_cannot_follow_a_write_without_with():
    row = name("row")
    with pytest.raises(InvalidClauseOrderError):
        returning(lit(1)).unwind(param("rows"), row)
    with pytest.raises(InvalidClauseOrderError):
        create(node("Person", name="p")).unwind(param("rows"), row)
    with pytest.raises(DslError, match="RETURN"):
        unwind(param("rows"), row).build()


def test_union_branches_keep_their_own_bound_node_state_after_unwind():
    row = name("row")
    person = node("Person", name="p", properties={"uid": row["uid"]})
    first = unwind(param("rows_a", [{"uid": "p1"}]), row).create(person).returning(person)
    second = unwind(param("rows_b", [{"uid": "p2"}]), row).create(person).returning(person)
    assert _render(union(first, second)).cypher == (
        "UNWIND $rows_a AS `row` CREATE (p:Person {uid: `row`.uid}) RETURN p "
        "UNION UNWIND $rows_b AS `row` CREATE (p:Person {uid: `row`.uid}) RETURN p"
    )


def test_directly_constructed_unwind_applies_the_same_checks():
    row = name("row")
    statement = Statement((UnwindClause(param("rows"), row), ReturnClause((row["uid"],))))
    assert _render(statement).cypher == "UNWIND $rows AS `row` RETURN `row`.uid"
    with pytest.raises(DslError, match="variable"):
        UnwindClause(param("rows"), lit("row"))
    with pytest.raises(DslError, match="expression"):
        UnwindClause(1, row)
    with pytest.raises(InvalidIdentifierError):
        UnwindClause(param("rows"), Variable(SymbolicName("")))
    with pytest.raises(InvalidClauseOrderError):
        Statement(
            (
                CreateClause((node("Person", name="p"),)),
                UnwindClause(param("rows"), row),
                ReturnClause((row,)),
            )
        )


def test_a_bulk_create_and_a_bulk_merge_can_share_one_read_prefix():
    row = name("row")
    person = node("Person", name="p", properties={"uid": row["uid"]})
    prefix = match(node("Account", name="a"))
    created = prefix.with_(name("a")).unwind(param("rows", [{"uid": "p1"}]), row).create(person).returning(person)
    assert _render(created).cypher == (
        "MATCH (a:Account) WITH a UNWIND $rows AS `row` CREATE (p:Person {uid: `row`.uid}) RETURN p"
    )


def test_upstream_leading_unwind():
    # Pinned: UNWIND [1, true, false] AS n RETURN n
    variable = name("n")
    query = unwind([1, True, False], variable).returning(variable)
    rendered = Renderer.get(Configuration(server_version="5.26", always_escape_names=True)).render(query)
    assert rendered.cypher == "UNWIND [1, true, false] AS `n` RETURN `n`"

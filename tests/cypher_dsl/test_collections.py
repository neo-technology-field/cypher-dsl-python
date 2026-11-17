"""
List and map expressions built from child syntax.

A collection is an expression, not frozen data. Its contents stay child nodes, so
traversal reaches a nested parameter or subscript and rendering never turns a value into
opaque text. Map insertion order is part of the rendered output because the caller chose
it.
"""

from __future__ import annotations

import pytest

from cypher_dsl import (
    Configuration,
    ListExpression,
    MapExpression,
    MatchClause,
    MergeClause,
    Parameter,
    Renderer,
    ReturnClause,
    Statement,
    SymbolicName,
    create,
    list_,
    lit,
    map_,
    match,
    merge,
    name,
    node,
    optional_match,
    param,
    returning,
    union,
)
from cypher_dsl.errors import ConflictingParameterError, DslError, InvalidIdentifierError
from cypher_dsl.ast import _Visitor


def _render(value):
    return Renderer.get(Configuration(server_version="5.26")).render(value)


def test_a_list_keeps_item_order_and_child_expressions():
    assert _render(returning(list_(name("a"), 2, param("b", 3)))).cypher == "RETURN [a, 2, $b]"


def test_empty_collections_render_their_literal_form():
    assert _render(returning(list_(), map_({}))).cypher == "RETURN [], {}"


def test_a_map_keeps_insertion_order_and_accepts_expression_values():
    row = name("row")
    expression = map_({"uid": row["uid"], "since": param("since", 2020)})
    rendered = _render(returning(expression))
    assert rendered.cypher == "RETURN {uid: `row`.uid, since: $since}"
    assert rendered.parameters == {"since": 2020}


def test_nested_collections_and_dynamic_subscripts_stay_syntax():
    row = name("row")
    expression = list_(map_({"tags": row[param("tag_key", "tags")]}), list_(1, 2))
    rendered = _render(returning(expression))
    assert rendered.cypher == "RETURN [{tags: `row`[$tag_key]}, [1, 2]]"
    assert rendered.parameters == {"tag_key": "tags"}


def test_map_keys_are_quoted_as_names():
    assert _render(returning(map_({"name": "Ada"}))).cypher == "RETURN {`name`: 'Ada'}"


def test_traversal_reaches_parameters_inside_collections_and_subscripts():
    class Collector(_Visitor):
        def __init__(self):
            self.names = []

        def enter(self, node):
            if isinstance(node, Parameter):
                self.names.append(node.symbol.value)

    row = name("row")
    query = returning(list_(param("a", 1), map_({"b": row[param("c", "uid")], "d": param("e", 2)})))
    collector = Collector()
    query.build().accept(collector)
    assert collector.names == ["a", "c", "e"]


def test_collection_parameters_obey_binding_conflict_rules_across_a_union():
    with pytest.raises(ConflictingParameterError):
        _render(union(returning(list_(param("p", 1))), returning(list_(param("p", 2)))))


def test_conflicting_bindings_inside_one_collection_tree_are_rejected():
    with pytest.raises(ConflictingParameterError):
        _render(returning(map_({"a": param("p", 1), "b": param("p", 2)})))


def test_a_map_expression_can_stand_in_a_create_property_position():
    alice = node("Person", name="a")
    bob = node("Person", name="b")
    hop = alice.relationship_to(bob, "KNOWS", name="k", properties=map_({"since": 2020}))
    assert _render(create(alice, hop)).cypher == ("CREATE (a:Person), (a)-[k:KNOWS {since: 2020}]->(b:Person)")
    with pytest.raises(DslError, match="map"):
        create(node("Person", name="p", properties=list_(1, 2)))


def test_a_map_expression_supplies_explicit_match_and_merge_properties():
    alice = node("Person", name="a", properties=map_({"uid": param("uid", "p1")}))
    bob = node("Person", name="b")
    assert _render(match(alice).returning(alice)).cypher == "MATCH (a:Person {uid: $uid}) RETURN a"
    assert _render(optional_match(alice).returning(alice)).cypher == "OPTIONAL MATCH (a:Person {uid: $uid}) RETURN a"
    assert _render(merge(alice).returning(alice)).cypher == "MERGE (a:Person {uid: $uid}) RETURN a"

    hop = alice.relationship_to(bob, "KNOWS", name="k", properties=map_({"since": param("since", 2020)}))
    assert _render(match(hop).returning(name("k"))).cypher == (
        "MATCH (a:Person {uid: $uid})-[k:KNOWS {since: $since}]->(b:Person) RETURN k"
    )
    assert _render(merge(hop).returning(name("k"))).cypher == (
        "MERGE (a:Person {uid: $uid})-[k:KNOWS {since: $since}]->(b:Person) RETURN k"
    )


def test_directly_constructed_match_and_merge_accept_a_map_expression():
    person = node("Person", name="p", properties=map_({"uid": param("uid", "p1")}))
    matched = Statement((MatchClause((person,)), ReturnClause((person.as_expression(),))))
    assert _render(matched).cypher == "MATCH (p:Person {uid: $uid}) RETURN p"
    merged = Statement((MergeClause(person),))
    assert _render(merged).cypher == "MERGE (p:Person {uid: $uid})"


def test_match_and_merge_keep_rejecting_whole_map_expressions():
    whole_map = node("Person", name="p", properties=param("props", {"uid": "p1"}))
    for builder in (match, optional_match, merge):
        with pytest.raises(DslError, match="whole-map"):
            builder(whole_map)
    with pytest.raises(DslError, match="whole-map"):
        match(node("Person", name="p", properties=name("props")))
    with pytest.raises(DslError, match="whole-map"):
        merge(node("Person", name="p", properties=list_(1, 2)))
    with pytest.raises(DslError, match="whole-map"):
        MatchClause((whole_map,))
    with pytest.raises(DslError, match="whole-map"):
        MergeClause(whole_map)


def test_a_binding_in_one_union_branch_resolves_another_branchs_occurrence():
    rendered = _render(union(returning(list_(param("p", [1]))), returning(map_({"v": param("p")}))))
    assert rendered.cypher == "RETURN [$p] UNION RETURN {v: $p}"
    assert rendered.parameters == {"p": [1]}
    assert rendered.unbound_parameters == frozenset()


def test_a_map_snapshots_its_input_mapping():
    data = {"uid": "p1"}
    expression = map_(data)
    data["uid"] = "changed"
    assert _render(returning(expression)).cypher == "RETURN {uid: 'p1'}"


def test_a_list_snapshots_its_items():
    items = [lit(1)]
    expression = list_(*items)
    items.append(lit(2))
    assert _render(returning(expression)).cypher == "RETURN [1]"


def test_a_map_rejects_duplicate_and_invalid_keys():
    with pytest.raises(DslError, match="Duplicate"):
        MapExpression(((SymbolicName("a"), lit(1)), (SymbolicName("a"), lit(2))))
    with pytest.raises(InvalidIdentifierError):
        map_({"": 1})
    with pytest.raises(DslError, match="keys must be strings"):
        map_({1: 2})


def test_collections_reject_aliases_and_non_expression_fields():
    with pytest.raises(DslError, match="alias"):
        list_(lit(1).alias("x"))
    with pytest.raises(DslError, match="alias"):
        MapExpression(((SymbolicName("a"), lit(1).alias("x")),))
    with pytest.raises(DslError, match="tuple"):
        ListExpression([lit(1)])
    with pytest.raises(DslError, match="tuple"):
        MapExpression({SymbolicName("a"): lit(1)})
    with pytest.raises(DslError, match="expression"):
        ListExpression((1,))
    with pytest.raises(DslError, match="expression"):
        MapExpression(((SymbolicName("a"), 1),))


def test_directly_constructed_collections_carry_their_entries():
    expression = MapExpression(((SymbolicName("a"), lit(1)), (SymbolicName("b"), lit(2))))
    assert _render(returning(expression)).cypher == "RETURN {a: 1, b: 2}"
    assert isinstance(ListExpression((lit(1),)), ListExpression)

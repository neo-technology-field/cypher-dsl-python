# Ported from the Java Cypher-DSL test suite (neo4j/cypher-dsl, Apache-2.0).
# Traced source: CypherIT. Rewritten for pytest.
"""
Write clauses, updates and deletion.

The tests pin what each update form means, which targets are expressions rather than
data, and when a write statement is complete. A write is a terminal clause: a statement that
creates, updates or deletes needs no dummy ``RETURN``, while a read that stops at
``MATCH`` is still incomplete.
"""

from __future__ import annotations

import pytest

from cypher_dsl import (
    Assignment,
    Comparison,
    Configuration,
    CreateClause,
    DeleteClause,
    LabelUpdate,
    Language,
    MatchClause,
    MergeClause,
    Relationship,
    RelationshipDirection,
    RelationshipPattern,
    Renderer,
    SetClause,
    Statement,
    StatementBuilder,
    UpdateKind,
    assign,
    create,
    lit,
    match,
    merge,
    name,
    node,
    param,
    set_labels,
    union,
    update_properties,
)
from cypher_dsl.errors import (
    DslError,
    EmptyPatternError,
    InvalidClauseOrderError,
    InvalidIdentifierError,
)


def render(value: Statement | StatementBuilder) -> str:
    return Renderer.get(Configuration(server_version="5.26")).render(value).cypher


def test_create_many_nodes_keeps_pattern_order():
    alice = node("Person", name="a", properties={"given": "Alice"})
    bob = node("Person", name="b", properties={"given": "Bob"})
    assert render(create(alice, bob)) == "CREATE (a:Person {given: 'Alice'}), (b:Person {given: 'Bob'})"


def test_create_relationship_property_maps_render_on_both_ends():
    alice = node("Person", name="a", properties={"given": "Alice"})
    acme = node("Company", name="c")
    works = alice.relationship_to(acme, "WORKS_AT", name="w", properties={"since": 2020})
    assert render(create(alice, works)) == (
        "CREATE (a:Person {given: 'Alice'}), (a)-[w:WORKS_AT {since: 2020}]->(c:Company)"
    )


def test_create_accepts_a_whole_map_parameter():
    person = node("Person", name="p", properties=param("props", {"given": "Ada"}))
    result = Renderer.get(Configuration(server_version="5.26")).render(create(person))
    assert result.cypher == "CREATE (p:Person $props)"
    assert result.parameters == {"props": {"given": "Ada"}}


def test_match_and_merge_reject_a_whole_map_pattern():
    person = node("Person", name="p", properties=param("props", {"uid": "p1"}))
    with pytest.raises(DslError, match="whole-map"):
        match(person)
    with pytest.raises(DslError, match="whole-map"):
        merge(person)


def test_create_needs_at_least_one_pattern():
    with pytest.raises(EmptyPatternError):
        create()
    with pytest.raises(EmptyPatternError):
        StatementBuilder().create()


def test_labels_are_added_and_removed_through_label_updates():
    person = node("Person", name="p")
    assert render(match(person).set_(set_labels(person, "Employee", "Staff"))) == (
        "MATCH (p:Person) SET p:Employee:Staff"
    )
    assert render(match(person).remove(set_labels(person, "Employee"))) == "MATCH (p:Person) REMOVE p:Employee"


def test_set_combines_property_and_label_updates_in_one_clause():
    person = node("Person", name="p")
    query = match(person).set_(assign(person["given"], "Ada"), set_labels(person, "Employee"))
    assert render(query) == "MATCH (p:Person) SET p.given = 'Ada', p:Employee"


def test_remove_deletes_a_property_reference():
    person = node("Person", name="p")
    assert render(match(person).remove(person["nickname"])) == "MATCH (p:Person) REMOVE p.nickname"


def test_delete_accepts_multiple_named_targets():
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    assert render(match(person, movie).delete(person, movie)) == "MATCH (p:Person), (m:Movie) DELETE p, m"
    assert render(match(person).detach_delete(person)) == "MATCH (p:Person) DETACH DELETE p"


def test_remove_rejects_a_literal_and_delete_rejects_arithmetic():
    person = node("Person", name="p")
    with pytest.raises(DslError, match="property"):
        match(person).remove(lit("nickname"))
    with pytest.raises(DslError, match="element reference"):
        match(person).delete(person["score"] + 1)


def test_assignment_rejects_a_target_that_is_not_a_reference():
    for target in (1, "p", lit("p")):
        with pytest.raises(DslError, match="target"):
            assign(target, 1)


def test_equality_builds_a_predicate_not_an_assignment():
    person = node("Person", name="p")
    predicate = person["given"] == "Ada"
    update = assign(person["given"], "Ada")
    assert isinstance(predicate, Comparison)
    assert isinstance(update, Assignment)
    assert render(match(person).where(predicate).returning(person)) == (
        "MATCH (p:Person) WHERE p.given = 'Ada' RETURN p"
    )


def test_return_less_terminal_writes_are_complete():
    person = node("Person", name="p")
    assert render(create(person)) == "CREATE (p:Person)"
    assert render(merge(person)) == "MERGE (p:Person)"
    assert render(match(person).set_(assign(person["given"], "Ada"))) == "MATCH (p:Person) SET p.given = 'Ada'"
    assert render(match(person).remove(person["given"])) == "MATCH (p:Person) REMOVE p.given"
    assert render(match(person).delete(person)) == "MATCH (p:Person) DELETE p"


def test_a_read_ending_in_match_is_still_incomplete():
    person = node("Person", name="p")
    with pytest.raises(DslError, match="RETURN"):
        match(person).build()


def test_a_match_cannot_follow_a_write_without_a_with_boundary():
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    with pytest.raises(InvalidClauseOrderError):
        create(person).match(movie)
    query = create(person).with_(person).match(person.relationship_to(movie, "LIKES", name="r")).returning(person)
    assert render(query) == "CREATE (p:Person) WITH p MATCH (p:Person)-[r:LIKES]->(m:Movie) RETURN p"


def test_union_branches_do_not_share_bound_node_state():
    person = node("Person", name="p")
    read = match(person).returning(person)
    created = create(person).returning(person)
    assert render(created) == "CREATE (p:Person) RETURN p"
    assert render(union(read, created)) == "MATCH (p:Person) RETURN p UNION CREATE (p:Person) RETURN p"


def test_union_all_branches_do_not_share_bound_merge_state():
    person = node("Person", name="p")
    read = match(person).returning(person)
    merged = merge(person).returning(person)
    assert render(merged) == "MERGE (p:Person) RETURN p"
    assert render(union(read, merged, all=True)) == "MATCH (p:Person) RETURN p UNION ALL MERGE (p:Person) RETURN p"


def test_create_rejects_a_property_value_that_is_not_a_map_or_parameter():
    for properties in (lit(1), name("props")):
        with pytest.raises(DslError, match="whole-map parameter"):
            create(node("Person", name="x", properties=properties))
        with pytest.raises(DslError, match="whole-map parameter"):
            create(node("Person", name="x").relationship_to(node("Movie", name="m"), "LIKES", properties=properties))


def test_create_accepts_a_whole_map_parameter_on_a_relationship():
    person = node("Person", name="a")
    company = node("Company", name="c")
    works = person.relationship_to(company, "WORKS_AT", name="w", properties=param("relProps", {"since": 2020}))
    result = Renderer.get(Configuration(server_version="5.26")).render(create(works))
    assert result.cypher == "CREATE (a:Person)-[w:WORKS_AT $relProps]->(c:Company)"
    assert result.parameters == {"relProps": {"since": 2020}}


def test_create_rejects_a_projection_alias_as_pattern_properties():
    with pytest.raises(DslError, match="whole-map parameter"):
        CreateClause((node("Person", name="x", properties=param("props").alias("data")),))


def test_create_preserves_literal_map_properties():
    literal = lit({"uid": 1})
    node_statement = Statement((CreateClause((node("Person", name="p", properties=literal),)),))
    assert render(node_statement) == "CREATE (p:Person {uid: 1})"

    person = node("Person", name="a")
    other = node("Person", name="b")
    rel = person.relationship_to(other, "KNOWS", name="r", properties=literal)
    assert render(create(rel)) == "CREATE (a:Person)-[r:KNOWS {uid: 1}]->(b:Person)"


def test_patch_requires_a_variable_target():
    person = node("Person", name="p")
    assert render(match(person).set_(update_properties(person, param("props", {"given": "Ada"})))) == (
        "MATCH (p:Person) SET p += $props"
    )
    with pytest.raises(DslError, match="binding variable"):
        update_properties(person["given"], param("props", {}))
    with pytest.raises(DslError, match="binding variable"):
        Assignment(person[param("key")], param("props", {}), UpdateKind.PATCH)


def test_create_rejects_an_undirected_relationship():
    person = node("Person", name="a")
    other = node("Person", name="b")
    with pytest.raises(DslError, match="direction"):
        create(person.relationship_with(other, "KNOWS", name="r"))


def test_create_rejects_a_relationship_without_a_type():
    person = node("Person", name="a")
    other = node("Person", name="b")
    hop = Relationship(person, other, RelationshipDirection.OUTGOING)
    with pytest.raises(DslError, match="relationship type"):
        CreateClause((RelationshipPattern((hop,)),))


def test_merge_keeps_undirected_relationship_support():
    person = node("Person", name="a")
    other = node("Person", name="b")
    query = merge(person.relationship_with(other, "KNOWS", name="r")).returning(person)
    assert render(query) == "MERGE (a:Person)-[r:KNOWS]-(b:Person) RETURN a"


def test_label_updates_reject_a_relationship_pattern():
    person = node("Person", name="a")
    other = node("Person", name="b")
    rel = person.relationship_to(other, "KNOWS", name="r")
    with pytest.raises(DslError, match="relationship"):
        match(rel).set_(set_labels(rel, "Staff"))
    with pytest.raises(DslError, match="relationship"):
        match(rel).remove(set_labels(rel, "Staff"))


def test_label_updates_reject_an_undeclared_conversion():
    class UndeclaredTarget:
        def as_expression(self):
            raise AssertionError("An undeclared conversion must not be called.")

    with pytest.raises(DslError, match="label update target"):
        set_labels(UndeclaredTarget(), "Reviewed")


def test_merge_references_endpoints_bound_by_the_preceding_match():
    first = node("Person", name="a", properties={"uid": param("a", "a1")})
    second = node("Person", name="b", properties={"uid": param("b", "b1")})
    query = match(first, second).merge(first.relationship_to(second, "KNOWS", name="r", properties={"since": 2020}))
    result = Renderer.get(Configuration(server_version="5.26")).render(query)
    assert result.cypher == ("MATCH (a:Person {uid: $a}), (b:Person {uid: $b}) MERGE (a)-[r:KNOWS {since: 2020}]->(b)")
    assert result.parameters == {"a": "a1", "b": "b1"}


def test_create_references_endpoints_bound_by_the_preceding_match():
    person = node("Person", name="a")
    company = node("Company", name="c")
    query = match(person, company).create(person.relationship_to(company, "WORKS_AT", name="w"))
    assert render(query) == "MATCH (a:Person), (c:Company) CREATE (a)-[w:WORKS_AT]->(c)"


def test_a_binding_kept_by_with_is_still_a_reference():
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    query = match(person).with_(person).merge(person.relationship_to(movie, "LIKES", name="r"))
    assert render(query) == "MATCH (p:Person) WITH p MERGE (p)-[r:LIKES]->(m:Movie)"


def test_a_conflicting_redefinition_is_not_suppressed():
    person = node("Person", name="p", properties={"uid": 1})
    employee = node("Employee", name="p", properties={"uid": 1})
    with pytest.raises(DslError, match="bound standalone"):
        match(person).merge(employee)


@pytest.mark.parametrize("operation", ["create", "merge"])
@pytest.mark.parametrize("direct", [False, True])
def test_write_cannot_redeclare_a_bound_standalone_node(operation, direct):
    person = node("Person", name="p")
    with pytest.raises(DslError, match="bound standalone"):
        if direct:
            write = CreateClause((person,)) if operation == "create" else MergeClause(person)
            Statement((MatchClause((person,)), write))
        else:
            getattr(match(person), operation)(person)


@pytest.mark.parametrize("operation", ["create", "merge"])
@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize("conflict", ["label", "property"])
def test_write_rejects_a_conflicting_bound_endpoint(operation, direct, conflict):
    person = node("Person", name="p", properties={"uid": 1})
    other = node("Person", name="q")
    changed = node(
        "Employee" if conflict == "label" else "Person",
        name="p",
        properties={"uid": 1 if conflict == "label" else 2},
    )
    relationship = changed.relationship_to(other, "KNOWS")
    with pytest.raises(DslError, match="conflicting declaration"):
        if direct:
            write = CreateClause((relationship,)) if operation == "create" else MergeClause(relationship)
            Statement((MatchClause((person,)), write))
        else:
            getattr(match(person), operation)(relationship)


@pytest.mark.parametrize("operation", ["create", "merge"])
def test_write_preserves_equivalent_bound_endpoints_after_an_alias(operation):
    person = node("Person", name="p", properties={"uid": 1})
    alias = node("Person", name="a", properties={"uid": 1})
    other = node("Person", name="q")
    query = getattr(match(person).with_(person.as_expression().alias("a")), operation)(
        alias.relationship_to(other, "KNOWS")
    )
    assert render(query) == (f"MATCH (p:Person {{uid: 1}}) WITH p AS a {operation.upper()} (a)-[:KNOWS]->(q:Person)")


@pytest.mark.parametrize("operation", ["create", "merge"])
def test_write_rejects_an_already_bound_relationship_variable(operation):
    person = node("Person", name="p")
    other = node("Person", name="q")
    relationship = person.relationship_to(other, "KNOWS", name="r")
    with pytest.raises(DslError, match="bound relationship"):
        getattr(match(relationship), operation)(relationship)


def test_create_rejects_conflicting_declarations_in_the_same_clause():
    person = node("Person", name="p")
    employee = node("Employee", name="p")
    with pytest.raises(DslError, match="conflicting declaration"):
        create(person, employee.relationship_to(node("Company", name="c"), "WORKS_AT"))


@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize("multi_hop", [False, True])
def test_merge_requires_a_type_on_every_relationship(direct, multi_hop):
    first, second, third = (node("Person", name=value) for value in ("a", "b", "c"))
    untyped = Relationship(second if multi_hop else first, third, RelationshipDirection.OUTGOING)
    hops = (first.relationship_to(second, "KNOWS").relationships[0], untyped) if multi_hop else (untyped,)
    pattern = RelationshipPattern(hops)
    with pytest.raises(DslError, match=r"MERGE.*type"):
        MergeClause(pattern) if direct else merge(pattern)


def test_untyped_match_and_typed_undirected_merge_remain_valid():
    first, second = node("Person", name="a"), node("Person", name="b")
    untyped = RelationshipPattern((Relationship(first, second, RelationshipDirection.UNDIRECTED),))
    assert render(match(untyped).returning(first)) == "MATCH (a:Person)--(b:Person) RETURN a"
    assert render(merge(first.relationship_with(second, "KNOWS"))) == "MERGE (a:Person)-[:KNOWS]-(b:Person)"


@pytest.mark.parametrize("operation", ["create", "merge"])
def test_a_write_hop_may_leave_the_relationship_variable_out(operation):
    person, other = node("Person", name="a"), node("Person", name="b")
    statement = getattr(match(person), operation)(person.relationship_to(other, "KNOWS"))
    assert render(statement) == f"MATCH (a:Person) {operation.upper()} (a)-[:KNOWS]->(b:Person)"


def _dynamic_write(operation):
    person = node("Person", name="p")
    target = person[param("key", "given")]
    if operation == "set":
        return match(person).set_(assign(target, "Ada"))
    if operation == "remove":
        return match(person).remove(target)
    return getattr(merge(person), operation)(assign(target, "Ada"))


@pytest.mark.parametrize("operation", ["set", "remove", "on_create", "on_match"])
@pytest.mark.parametrize(
    ("version", "language", "prefix"),
    [
        ("5.26", Language.AUTO, ""),
        ("5.26", Language.NONE, ""),
        ("5.26", Language.CYPHER_5, "CYPHER 5 "),
        ("2026.10", Language.CYPHER_25, "CYPHER 25 "),
        ("2025.01", Language.AUTO, ""),
    ],
)
def test_dynamic_property_writes_accept_compatible_targets(operation, version, language, prefix):
    configuration = Configuration(server_version=version, language=language)
    result = Renderer.get(configuration).render(_dynamic_write(operation))
    expected = {
        "set": "MATCH (p:Person) SET p[$key] = 'Ada'",
        "remove": "MATCH (p:Person) REMOVE p[$key]",
        "on_create": "MERGE (p:Person) ON CREATE SET p[$key] = 'Ada'",
        "on_match": "MERGE (p:Person) ON MATCH SET p[$key] = 'Ada'",
    }
    assert result.cypher == prefix + expected[operation]
    assert result.parameters == {"key": "given"}


def test_dynamic_property_reads_are_not_restricted_by_the_write_floor():
    person = node("Person", name="p")
    result = Renderer.get(Configuration(server_version="5.26")).render(
        match(person).returning(person[param("key", "given")])
    )
    assert result.cypher == "MATCH (p:Person) RETURN p[$key]"
    assert result.parameters == {"key": "given"}


def test_dynamic_reads_in_static_assignments_do_not_require_dynamic_writes():
    person = node("Person", name="p")
    result = Renderer.get(Configuration(server_version="5.26")).render(
        match(person).set_(assign(person["copied"], person[param("key", "given")]))
    )
    assert result.cypher == "MATCH (p:Person) SET p.copied = p[$key]"
    assert result.parameters == {"key": "given"}


def test_a_binding_dropped_by_with_is_rendered_as_a_new_pattern():
    person = node("Person", name="p")
    other = node("Person", name="q")
    movie = node("Movie", name="m")
    query = match(person, other).with_(person).merge(other.relationship_to(movie, "LIKES", name="r"))
    assert render(query) == "MATCH (p:Person), (q:Person) WITH p MERGE (q:Person)-[r:LIKES]->(m:Movie)"


def test_a_set_reference_to_a_discarded_name_is_rejected():
    person = node("Person", name="p")
    other = node("Person", name="q")
    with pytest.raises(DslError, match="not in scope"):
        match(person, other).with_(person).set_(assign(other["given"], "Ada"))


def test_directly_constructed_write_clauses_apply_the_same_checks():
    person = node("Person", name="p")
    statement = Statement((MatchClause((person,)), SetClause((assign(person["given"], "Ada"),))))
    assert (
        Renderer.get(Configuration(server_version="5.26")).render(statement).cypher
        == "MATCH (p:Person) SET p.given = 'Ada'"
    )

    with pytest.raises(DslError, match="element reference"):
        DeleteClause((lit("p"),))
    with pytest.raises(InvalidClauseOrderError):
        Statement((CreateClause((person,)), MatchClause((node("Movie", name="m"),))))
    with pytest.raises(InvalidClauseOrderError):
        Statement((SetClause((assign(person["given"], "Ada"),)),))


def test_updated_targets_must_be_references():
    person = node("Person", name="p")
    with pytest.raises(DslError, match="target"):
        update_properties(lit("p"), param("props", {}))
    with pytest.raises(DslError, match="label"):
        set_labels(person)
    with pytest.raises(InvalidIdentifierError):
        set_labels(person, "")
    assert isinstance(set_labels(person, "Employee"), LabelUpdate)


def test_set_and_action_calls_require_an_update():
    person = node("Person", name="p")
    with pytest.raises(DslError, match="SET"):
        match(person).set_()
    assert render(merge(person).on_create(assign(person["created"], True))) == (
        "MERGE (p:Person) ON CREATE SET p.created = true"
    )


def test_writes_are_immutable_branches():
    person = node("Person", name="p")
    prefix = match(person)
    created = prefix.create(node("Movie", name="m"))
    updated = prefix.set_(assign(person["given"], "Ada"))
    assert render(prefix.returning(person)) == "MATCH (p:Person) RETURN p"
    assert render(created) == "MATCH (p:Person) CREATE (m:Movie)"
    assert render(updated) == "MATCH (p:Person) SET p.given = 'Ada'"


def _render_forced_escaping(query):
    """
    Render with the Python equivalent of the pinned Java default configuration.

    Forced escaping also reaches variables, property keys and relationship variables here,
    unlike the pinned Java renderer, so the ported text carries extra backticks. The pinned
    expectation stays in a comment.
    """
    return Renderer.get(Configuration(server_version="5.26", always_escape_names=True)).render(query).cypher


def test_upstream_create_without_a_return():
    # Pinned: CREATE (u:`User`) and CREATE (u:`User`)-[o:`OWNS`]->(b:`Bike`)
    user = node("User", name="u")
    bike = node("Bike", name="b")
    assert _render_forced_escaping(create(user)) == "CREATE (`u`:`User`)"
    assert _render_forced_escaping(create(user.relationship_to(bike, "OWNS", name="o"))) == (
        "CREATE (`u`:`User`)-[`o`:`OWNS`]->(`b`:`Bike`)"
    )


def test_upstream_create_after_match_references_the_bound_node():
    # Pinned: MATCH (u:`User`) CREATE (u)-[o:`OWNS`]->(b:`Bike`)
    user = node("User", name="u")
    bike = node("Bike", name="b")
    assert _render_forced_escaping(match(user).create(user.relationship_to(bike, "OWNS", name="o"))) == (
        "MATCH (`u`:`User`) CREATE (`u`)-[`o`:`OWNS`]->(`b`:`Bike`)"
    )


def test_upstream_merge_after_match_references_the_bound_node():
    # Pinned: MATCH (u:`User`) MERGE (u)-[o:`OWNS`]->(b:`Bike`)
    user = node("User", name="u")
    bike = node("Bike", name="b")
    assert _render_forced_escaping(match(user).merge(user.relationship_to(bike, "OWNS", name="o"))) == (
        "MATCH (`u`:`User`) MERGE (`u`)-[`o`:`OWNS`]->(`b`:`Bike`)"
    )


@pytest.mark.parametrize("operation", ["create", "merge"])
def test_write_rejects_an_untyped_hop_from_the_factory(operation):
    person = node("Person", name="p")
    other = node("Person", name="q")
    with pytest.raises(DslError, match=rf"{operation.upper()} relationships need exactly one"):
        getattr(match(person), operation)(person.relationship_to(other))

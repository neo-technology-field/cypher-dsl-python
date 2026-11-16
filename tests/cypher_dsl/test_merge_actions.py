# Ported from the Java Cypher-DSL test suite (neo4j/cypher-dsl, Apache-2.0).
# Traced source: CypherIT. Rewritten for pytest.
"""
``MERGE`` actions and the two property update forms.

A merge has one identity pattern and zero or more actions. Identity is what the server
searches for, so it is written in the pattern and never inferred from the updates that
follow. The two update forms stay distinct types: ``SET n = $map`` replaces every
property, while ``SET n += $map`` patches the ones the map contains.
"""

from __future__ import annotations

import pytest

from cypher_dsl import (
    Configuration,
    MergeAction,
    MergeClause,
    Renderer,
    Statement,
    assign,
    create,
    match,
    merge,
    node,
    param,
    update_properties,
)
from cypher_dsl.errors import DslError, InvalidClauseOrderError


def test_merge_actions_keep_identity_separate_from_updates():
    person = node("Person", name="p", properties={"uid": param("uid", "p1")})
    query = (
        merge(person)
        .on_create(assign(person["created"], param("created", "2026-11-13")))
        .on_match(assign(person["seen"], param("seen", "2026-11-13")))
        .returning(person["uid"])
    )
    result = Renderer.get(Configuration(server_version="5.26")).render(query)
    assert result.cypher == (
        "MERGE (p:Person {uid: $uid}) ON CREATE SET p.created = $created ON MATCH SET p.seen = $seen RETURN p.uid"
    )
    assert result.parameters["uid"] == "p1"


def test_map_replace_and_patch_are_distinct():
    person = node("Person", name="p")
    renderer = Renderer.get(Configuration(server_version="5.26"))
    replace = match(person).set_(assign(person, param("properties", {"name": "Ada"})))
    patch = match(person).set_(update_properties(person, param("properties", {"name": "Ada"})))
    assert renderer.render(replace).cypher == "MATCH (p:Person) SET p = $properties"
    assert renderer.render(patch).cypher == "MATCH (p:Person) SET p += $properties"


def test_merge_identity_is_not_inferred_from_the_updates():
    person = node("Person", name="p", properties={"uid": param("uid")})
    query = merge(person).on_match(assign(person["given"], param("given")), assign(person["age"], 42))
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MERGE (p:Person {uid: $uid}) ON MATCH SET p.given = $given, p.age = 42"
    )


def test_action_call_order_is_preserved():
    person = node("Person", name="p")
    query = merge(person).on_match(assign(person["seen"], True)).on_create(assign(person["created"], True))
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MERGE (p:Person) ON MATCH SET p.seen = true ON CREATE SET p.created = true"
    )


def test_a_second_action_of_the_same_kind_is_rejected():
    person = node("Person", name="p")
    query = merge(person).on_create(assign(person["created"], True))
    with pytest.raises(DslError, match="ON CREATE"):
        query.on_create(assign(person["other"], True))
    with pytest.raises(DslError, match="ON MATCH"):
        query.on_match(assign(person["seen"], True)).on_match(assign(person["other"], True))


def test_an_action_needs_the_merge_it_belongs_to():
    person = node("Person", name="p")
    with pytest.raises(InvalidClauseOrderError, match="MERGE"):
        create(person).on_create(assign(person["created"], True))
    with pytest.raises(InvalidClauseOrderError, match="MERGE"):
        match(person).on_match(assign(person["seen"], True))
    with pytest.raises(InvalidClauseOrderError, match="MERGE"):
        merge(person).on_create(assign(person["created"], True)).set_(assign(person["x"], 1)).on_match(
            assign(person["seen"], True)
        )


def test_an_action_requires_at_least_one_update():
    person = node("Person", name="p")
    with pytest.raises(DslError, match="ON CREATE"):
        merge(person).on_create()
    with pytest.raises(DslError, match="ON MATCH"):
        merge(person).on_match()


def test_directly_constructed_merge_actions_are_validated():
    person = node("Person", name="p")
    created = MergeAction("ON CREATE", (assign(person["created"], True),))
    with pytest.raises(DslError, match="ON CREATE"):
        MergeClause(person, (created, created))
    with pytest.raises(DslError, match="MERGE"):
        MergeAction("ON DELETE", (assign(person["created"], True),))
    assert Renderer.get(Configuration(server_version="5.26")).render(
        Statement((MergeClause(person, (created,)),))
    ).cypher == ("MERGE (p:Person) ON CREATE SET p.created = true")


def test_merge_rejects_a_whole_map_identity_pattern():
    person = node("Person", name="p", properties=param("props", {"uid": "p1"}))
    with pytest.raises(DslError, match="whole-map"):
        merge(person)


def test_an_action_after_with_is_validated_immediately():
    person = node("Person", name="p")
    other = node("Person", name="q")
    query = match(person, other).with_(person).merge(node("Person", name="saved"))
    with pytest.raises(DslError, match="not in scope"):
        query.on_create(assign(other["given"], "Ada"))


def _render_forced_escaping(query):
    """
    Render with the Python equivalent of the pinned Java default configuration.

    Forced escaping also reaches variables and property keys here, unlike the pinned Java
    renderer, so the ported text carries extra backticks. The pinned expectation stays in
    a comment.
    """
    return Renderer.get(Configuration(server_version="5.26", always_escape_names=True)).render(query).cypher


def test_upstream_single_on_create_action():
    # Pinned: MERGE (u:`User`) ON CREATE SET u.p = 'Hallo, Welt'
    user = node("User", name="u")
    assert _render_forced_escaping(merge(user).on_create(assign(user["p"], "Hallo, Welt"))) == (
        "MERGE (`u`:`User`) ON CREATE SET `u`.`p` = 'Hallo, Welt'"
    )


def test_upstream_single_on_match_action():
    # Pinned: MERGE (u:`User`) ON MATCH SET u.p = 'Hallo, Welt'
    user = node("User", name="u")
    assert _render_forced_escaping(merge(user).on_match(assign(user["p"], "Hallo, Welt"))) == (
        "MERGE (`u`:`User`) ON MATCH SET `u`.`p` = 'Hallo, Welt'"
    )


def test_upstream_two_actions_with_two_properties_each():
    # Pinned: MERGE (u:`User`) ON MATCH SET u.p1 = 'v1', u.p2 = 'v2' ON CREATE SET u.p3 = 'v3', u.p4 = 'v4'
    user = node("User", name="u")
    query = (
        merge(user)
        .on_match(assign(user["p1"], "v1"), assign(user["p2"], "v2"))
        .on_create(assign(user["p3"], "v3"), assign(user["p4"], "v4"))
    )
    assert _render_forced_escaping(query) == (
        "MERGE (`u`:`User`) ON MATCH SET `u`.`p1` = 'v1', `u`.`p2` = 'v2' "
        "ON CREATE SET `u`.`p3` = 'v3', `u`.`p4` = 'v4'"
    )


def test_upstream_merge_exposes_a_property_set():
    # Pinned: MERGE (n:`LABEL1`) SET n.x = 'y'
    label = node("LABEL1", name="n")
    assert _render_forced_escaping(merge(label).set_(assign(label["x"], "y"))) == (
        "MERGE (`n`:`LABEL1`) SET `n`.`x` = 'y'"
    )


def test_upstream_merge_exposes_a_property_removal():
    # Pinned: MERGE (n:`LABEL1`) REMOVE n.x
    label = node("LABEL1", name="n")
    assert _render_forced_escaping(merge(label).remove(label["x"])) == "MERGE (`n`:`LABEL1`) REMOVE `n`.`x`"

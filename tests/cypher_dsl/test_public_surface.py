"""
The public surface is rendered to expected text or answered as a value.

Every name in ``cypher_dsl.__all__`` is accounted for here: functions that build syntax have
an exact expected statement, functions that answer a question have an expected value, and
every public class is produced by one of those examples. Adding a public name fails this
file until an example exists, and changing a rendering rule fails it with the text that
changed.

The expectations are the contract, not a transcription of current output. A shape that
looks wrong here is wrong even if the renderer agrees with it.
"""

from __future__ import annotations

import inspect
import types
import typing

import cypher_dsl
from cypher_dsl import (
    Configuration,
    Language,
    RelationshipDirection,
    Renderer,
    SortOrder,
    UpdateKind,
    asc,
    assign,
    asterisk,
    boolean_operation,
    call_procedure,
    condition,
    count,
    create,
    desc,
    element_id,
    fn,
    in_,
    list_,
    lit,
    map_,
    match,
    merge,
    name,
    node,
    optional_call_procedure,
    optional_match,
    param,
    raw,
    returning,
    same_binding,
    set_labels,
    structurally_equal,
    thaw_value,
    union,
    unwind,
    update_properties,
    with_,
)

RENDERER = Renderer.get(Configuration(server_version="5.26"))

PERSON = node("Person", name="p")
MOVIE = node("Movie", name="m")

RENDERS: dict[str, tuple[object, str]] = {
    "asc": (
        match(PERSON).returning(PERSON["uid"]).order_by(asc(PERSON["uid"])),
        "MATCH (p:Person) RETURN p.uid ORDER BY p.uid ASC",
    ),
    "assign": (match(PERSON).set_(assign(PERSON["uid"], "p1")), "MATCH (p:Person) SET p.uid = 'p1'"),
    "asterisk": (
        match(PERSON).returning(count(asterisk()).alias("people")),
        "MATCH (p:Person) RETURN count(*) AS people",
    ),
    "boolean_operation": (
        match(PERSON).where(boolean_operation("AND", PERSON["age"] > 30, PERSON["years"] > 10)).returning(PERSON),
        "MATCH (p:Person) WHERE p.age > 30 AND p.years > 10 RETURN p",
    ),
    "call": (
        match(PERSON)
        .call(match(MOVIE).returning(MOVIE["title"].alias("title")), imports=("p",), in_transactions=5_000)
        .returning(name("title")),
        "MATCH (p:Person) CALL (p) { MATCH (m:Movie) RETURN m.title AS title } IN TRANSACTIONS OF 5000 ROWS"
        " RETURN title",
    ),
    "call_procedure": (call_procedure("db.labels"), "CALL db.labels()"),
    "condition": (
        match(PERSON).where(condition(PERSON["uid"] == "p1")).returning(PERSON),
        "MATCH (p:Person) WHERE p.uid = 'p1' RETURN p",
    ),
    "count": (returning(count(PERSON).alias("people")), "RETURN count(p) AS people"),
    "create": (create(node("Person", name="p", properties={"uid": "p1"})), "CREATE (p:Person {uid: 'p1'})"),
    "desc": (
        match(PERSON).returning(PERSON["uid"]).order_by(desc(PERSON["uid"])),
        "MATCH (p:Person) RETURN p.uid ORDER BY p.uid DESC",
    ),
    "element_id": (
        match(PERSON).returning(element_id(PERSON).alias("identity")),
        "MATCH (p:Person) RETURN elementId(p) AS identity",
    ),
    "fn": (returning(fn("toUpper", "ada").alias("loud")), "RETURN toUpper('ada') AS loud"),
    "in_": (
        match(PERSON).where(in_(PERSON["uid"], list_("p1", "p2"))).returning(PERSON),
        "MATCH (p:Person) WHERE p.uid IN ['p1', 'p2'] RETURN p",
    ),
    "list_": (returning(list_("p1", "p2").alias("ids")), "RETURN ['p1', 'p2'] AS ids"),
    "lit": (returning(lit("Ada").alias("who")), "RETURN 'Ada' AS who"),
    "map_": (returning(map_({"uid": "p1"}).alias("entry")), "RETURN {uid: 'p1'} AS entry"),
    "match": (
        match(PERSON).where(PERSON["uid"] == "p1").returning(PERSON["uid"]),
        "MATCH (p:Person) WHERE p.uid = 'p1' RETURN p.uid",
    ),
    "merge": (merge(PERSON).on_create(assign(PERSON["uid"], "p1")), "MERGE (p:Person) ON CREATE SET p.uid = 'p1'"),
    "name": (returning(name("total")), "RETURN total"),
    "node": (
        match(node("Person", name="p", properties={"uid": "p1"})).returning("p"),
        "MATCH (p:Person {uid: 'p1'}) RETURN p",
    ),
    "optional_call": (
        match(PERSON)
        .optional_call(match(MOVIE).returning(MOVIE["title"].alias("title")), imports=("p",), in_transactions=5_000)
        .returning(PERSON["uid"], name("title")),
        "MATCH (p:Person) OPTIONAL CALL (p) { MATCH (m:Movie) RETURN m.title AS title } IN TRANSACTIONS OF 5000"
        " ROWS RETURN p.uid, title",
    ),
    "optional_call_procedure": (
        optional_call_procedure("apoc.neighbors.tohop", param("start"), "KNOWS>", 1),
        "OPTIONAL CALL apoc.neighbors.tohop($start, 'KNOWS>', 1)",
    ),
    "optional_match": (optional_match(PERSON).returning(PERSON["uid"]), "OPTIONAL MATCH (p:Person) RETURN p.uid"),
    "param": (returning(param("uid", "p1")), "RETURN $uid"),
    "raw": (returning(raw("count(*) AS total")), "RETURN count(*) AS total"),
    "returning": (returning(name("total")), "RETURN total"),
    "set_labels": (match(PERSON).set_(set_labels(PERSON, "Member")), "MATCH (p:Person) SET p:Member"),
    "union": (
        union(match(PERSON).returning(PERSON["uid"].alias("uid")), match(MOVIE).returning(MOVIE["uid"].alias("uid"))),
        "MATCH (p:Person) RETURN p.uid AS uid UNION MATCH (m:Movie) RETURN m.uid AS uid",
    ),
    "unwind": (
        unwind(param("rows", [{"uid": "p1"}]), name("row")).returning(name("row")["uid"].alias("uid")),
        "UNWIND $rows AS `row` RETURN `row`.uid AS uid",
    ),
    "update_properties": (
        match(PERSON).set_(update_properties(PERSON, map_({"uid": "p1"}))),
        "MATCH (p:Person) SET p += {uid: 'p1'}",
    ),
    "with_": (
        with_(PERSON["uid"].alias("uid")).returning(name("uid")),
        "WITH p.uid AS uid RETURN uid",
    ),
}

VALUES: dict[str, tuple[object, object]] = {
    "same_binding": (same_binding(True, True), True),
    "structurally_equal": (
        structurally_equal(match(PERSON).returning(PERSON).build(), match(PERSON).returning(PERSON).build()),
        True,
    ),
    "freeze_value": (thaw_value(cypher_dsl.freeze_value([1, 2])), [1, 2]),
    "thaw_value": (thaw_value(cypher_dsl.freeze_value({"uid": "p1"})), {"uid": "p1"}),
}

EXTRA_OBJECTS = (
    Configuration(server_version="5.26"),
    RENDERER,
    RENDERER.render(match(PERSON).returning(PERSON)),
    Language.CYPHER_5,
    SortOrder.ASCENDING,
    RelationshipDirection.OUTGOING,
    UpdateKind.ASSIGN,
    match(PERSON).returning(PERSON).build(),
    match(PERSON).remove(PERSON["uid"]),
    match(PERSON).delete(PERSON),
    match(PERSON)
    .call(match(MOVIE).returning(MOVIE["title"].alias("title")), imports=("p",))
    .returning(name("title"))
    .build(),
    PERSON.relationship_to(MOVIE, "ACTED_IN", name="acted"),
    name("total"),
    cypher_dsl.SymbolicName("Person"),
    PERSON[param("key", "k")],
    -lit(1),
    cypher_dsl.UNBOUND,
)


def _is_type_alias(value: object) -> bool:
    """Return whether a public name is a union type alias rather than a callable.

    Before Python 3.14 a ``typing.Union`` alias is a callable that is not a
    ``types.UnionType``, while 3.14 unified the two representations. The alias kinds must
    therefore be recognised before the function set is built, on every supported version.
    """
    return typing.get_origin(value) in (typing.Union, types.UnionType)


def _public_functions() -> set[str]:
    return {
        name
        for name in cypher_dsl.__all__
        if callable(getattr(cypher_dsl, name))
        and not inspect.isclass(getattr(cypher_dsl, name))
        and not _is_type_alias(getattr(cypher_dsl, name))
    }


def _public_classes() -> set[str]:
    return {name for name in cypher_dsl.__all__ if inspect.isclass(getattr(cypher_dsl, name))}


def _walk(node: object) -> typing.Iterator[object]:
    yield node
    for child in getattr(node, "children", lambda: ())():
        yield from _walk(child)


def _produced() -> list[object]:
    produced = [value for value, _ in RENDERS.values()]
    produced.extend(value for value, _ in VALUES.values())
    produced.extend(EXTRA_OBJECTS)
    nodes: list[object] = []
    for value in list(produced):
        build = getattr(value, "build", None)
        if callable(build):
            produced.append(build())
    for value in produced:
        nodes.extend(_walk(value))
    return produced + nodes


def test_every_public_name_resolves() -> None:
    missing = [name for name in cypher_dsl.__all__ if not hasattr(cypher_dsl, name)]
    assert missing == []


def test_every_public_function_has_an_example() -> None:
    assert set(RENDERS) | set(VALUES) == _public_functions()


def test_rendered_statements_match_their_expectations() -> None:
    for function_name, (query, expected) in RENDERS.items():
        assert RENDERER.render(query).cypher == expected, function_name


def test_answered_values_match_their_expectations() -> None:
    for function_name, (produced, expected) in VALUES.items():
        assert produced == expected, function_name


def test_every_public_class_is_produced_by_an_example() -> None:
    produced = _produced()
    missing = [
        class_name
        for class_name in _public_classes()
        if not any(isinstance(value, getattr(cypher_dsl, class_name)) for value in produced)
    ]
    assert missing == []


def test_public_aliases_and_sentinels_are_declared_kinds() -> None:
    aliases = {name for name in cypher_dsl.__all__ if _is_type_alias(getattr(cypher_dsl, name))}
    assert aliases == {"ExpressionInput", "FrozenValue", "LiteralInput", "ProjectionInput", "RenderInput"}
    assert cypher_dsl.UNBOUND is not None and not callable(cypher_dsl.UNBOUND)

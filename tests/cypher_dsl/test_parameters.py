"""Explicit parameter bindings collected per render."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from cypher_dsl import Configuration, Renderer, lit, match, node, param, returning, structurally_equal
from cypher_dsl.errors import ConflictingParameterError, InvalidIdentifierError


def test_unbound_parameter_is_reported_and_not_bound():
    rendered = Renderer.get(Configuration(server_version="5.26")).render(returning(param("name")))
    assert rendered.cypher == "RETURN $name"
    assert rendered.parameters == {}
    assert rendered.unbound_parameters == frozenset({"name"})


def test_parameter_names_that_need_quoting_render_backticks():
    person = node("Person", name="p")
    default = Renderer.get(Configuration(server_version="5.26")).render(
        match(person).returning(param("request value", 1))
    )
    assert default.cypher == "MATCH (p:Person) RETURN $`request value`"
    forced = Renderer.get(Configuration(server_version="5.26", always_escape_names=True)).render(
        match(person).returning(param("value", 1))
    )
    assert forced.cypher == "MATCH (`p`:`Person`) RETURN $`value`"


def test_a_later_bound_occurrence_resolves_an_earlier_unbound_one():
    rendered = Renderer.get(Configuration(server_version="5.26")).render(returning(param("p"), param("p", 1)))
    assert rendered.cypher == "RETURN $p, $p"
    assert rendered.parameters == {"p": 1}
    assert rendered.unbound_parameters == frozenset()


def test_an_earlier_bound_occurrence_resolves_a_later_unbound_one():
    rendered = Renderer.get(Configuration(server_version="5.26")).render(returning(param("p", 1), param("p")))
    assert rendered.parameters == {"p": 1}
    assert rendered.unbound_parameters == frozenset()


def test_repeated_unbound_occurrences_collapse_to_one_name():
    rendered = Renderer.get(Configuration(server_version="5.26")).render(returning(param("p"), param("p"), param("q")))
    assert rendered.unbound_parameters == frozenset({"p", "q"})


def test_repeated_equal_bindings_produce_one_parameter():
    rendered = Renderer.get(Configuration(server_version="5.26")).render(
        returning(param("p", [1, {"a": 2}]), param("p", [1, {"a": 2}]))
    )
    assert rendered.parameters == {"p": [1, {"a": 2}]}


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (True, 1),
        (1, 1.0),
        (1, "1"),
        (None, 0),
        ("a", "b"),
        ([1], [2]),
        ({"a": 1}, {"a": 2}),
        ({"a": 1}, {"a": 1, "b": 2}),
    ],
)
def test_type_aware_bindings_conflict(left, right):
    query = returning(param("p", left), param("p", right))
    with pytest.raises(ConflictingParameterError, match="Conflicting bindings for"):
        Renderer.get(Configuration(server_version="5.26")).render(query)


@pytest.mark.parametrize("bound_first", [True, False])
def test_unbound_and_null_are_resolved_by_the_bound_occurrence(bound_first):
    occurrences = (param("p", None), param("p")) if bound_first else (param("p"), param("p", None))
    rendered = Renderer.get(Configuration(server_version="5.26")).render(returning(*occurrences))
    assert rendered.parameters == {"p": None}
    assert rendered.unbound_parameters == frozenset()


def test_an_unbound_occurrence_does_not_change_the_tree():
    query = returning(param("p"), param("p", 1))
    before = query.build()
    Renderer.get(Configuration(server_version="5.26")).render(query)
    assert structurally_equal(before, query.build())
    after = Renderer.get(Configuration(server_version="5.26")).render(query.build())
    assert after.unbound_parameters == frozenset()


class _ExplodingEquality:
    """Object whose equality must never be consulted while comparing bindings."""

    def __eq__(self, other: object) -> bool:
        raise AssertionError("third-party equality called")

    def __hash__(self) -> int:
        return id(self)


def test_conflicting_opaque_values_never_call_their_equality():
    first = _ExplodingEquality()
    second = _ExplodingEquality()
    query = returning(param("p", first), param("p", second))
    with pytest.raises(ConflictingParameterError):
        Renderer.get(Configuration(server_version="5.26")).render(query)


def test_the_same_opaque_object_twice_is_one_binding():
    value = _ExplodingEquality()
    rendered = Renderer.get(Configuration(server_version="5.26")).render(
        returning(param("p", value), param("p", value))
    )
    assert rendered.parameters == {"p": value}
    assert rendered.parameters["p"] is value


def test_statement_does_not_carry_a_parameter_bag():
    statement = returning(param("p", 1)).build()
    assert not hasattr(statement, "parameters")
    assert not hasattr(statement, "unbound_parameters")


def test_parameter_names_are_quoted_structurally():
    rendered = Renderer.get(Configuration(server_version="5.26")).render(returning(param("p OR true OR $q")))
    assert rendered.cypher == "RETURN $`p OR true OR $q`"
    escaped = Renderer.get(Configuration(server_version="5.26", always_escape_names=True)).render(
        returning(param("p", 1))
    )
    assert escaped.cypher == "RETURN $`p`"


def test_encoded_identifier_escapes_are_rejected_in_parameter_names():
    with pytest.raises(InvalidIdentifierError, match="escape"):
        Renderer.get(Configuration(server_version="5.26")).render(returning(param(r"p\u0060, 2 AS injected //")))


def test_reserved_parameter_names_stay_unquoted_after_the_dollar():
    assert (
        Renderer.get(Configuration(server_version="5.26")).render(returning(param("true", 1))).cypher == "RETURN $true"
    )


def test_parameters_and_literals_are_distinct():
    rendered = Renderer.get(Configuration(server_version="5.26")).render(returning(param("p", 1), lit(1)))
    assert rendered.cypher == "RETURN $p, 1"
    assert rendered.parameters == {"p": 1}


def test_each_render_owns_its_parameter_dictionary():
    renderer = Renderer.get(Configuration(server_version="5.26"))
    statement = returning(param("p", 1)).build()
    first = renderer.render(statement)
    second = renderer.render(statement)
    assert first.parameters == second.parameters == {"p": 1}
    assert first.parameters is not second.parameters
    first.parameters.clear()
    assert second.parameters == {"p": 1}
    assert renderer.render(statement).parameters == {"p": 1}


def test_one_renderer_keeps_bindings_per_concurrent_call():
    renderer = Renderer.get(Configuration(server_version="5.26"))
    statements = [(index, returning(param("value", index))) for index in range(8)]

    def render(item):
        index, statement = item
        return index, renderer.render(statement)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(render, statements))

    assert [index for index, _ in results] == list(range(8))
    for index, rendered in results:
        assert rendered.parameters == {"value": index}
        assert rendered.unbound_parameters == frozenset()

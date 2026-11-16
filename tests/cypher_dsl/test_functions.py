# Ported from the Java Cypher-DSL test suite (neo4j/cypher-dsl, Apache-2.0).
# Traced sources: FunctionsIT, IssueRelatedIT, DialectIT, CypherIT. Rewritten for pytest.
"""Function invocations, asterisks, element identifiers, raw text and sort items."""

from __future__ import annotations

import pytest

from cypher_dsl import (
    Asterisk,
    Configuration,
    ElementId,
    FunctionInvocation,
    Language,
    Literal,
    Renderer,
    SortItem,
    SortOrder,
    Variable,
    asc,
    asterisk,
    count,
    desc,
    element_id,
    fn,
    match,
    name,
    node,
    raw,
    returning,
)
from cypher_dsl.errors import DslError, InvalidIdentifierError


def _render(value, server_version="5.26", language=Language.AUTO):
    return Renderer.get(Configuration(server_version=server_version, language=language)).render(returning(value)).cypher


def test_generic_function_arguments_are_expressions():
    invocation = fn("coalesce", name("a"), "fallback")
    assert isinstance(invocation, FunctionInvocation)
    assert _render(invocation) == "RETURN coalesce(a, 'fallback')"


def test_bare_string_arguments_stay_literal_values():
    assert _render(fn("coalesce", "a", 1)) == "RETURN coalesce('a', 1)"


def test_zero_argument_functions_are_allowed():
    assert _render(fn("random")) == "RETURN random()"


def test_qualified_names_are_rendered_segment_by_segment():
    invocation = fn("point.distance", name("a"), name("b"))
    assert invocation.function_name == ("point", "distance")
    assert _render(invocation) == "RETURN point.distance(a, b)"


@pytest.mark.parametrize("function_name", ["", ".", ".point", "point.", "point..distance"])
def test_empty_function_name_segments_are_rejected(function_name):
    with pytest.raises(InvalidIdentifierError, match="segment"):
        fn(function_name)


def test_attack_shaped_function_segments_are_quoted():
    invocation = fn("x`) MATCH (n) //", name("a"))
    assert _render(invocation) == "RETURN `x``) MATCH (n) //`(a)"


def test_reserved_builtin_names_render_unquoted():
    assert _render(fn("id", name("n"))) == "RETURN id(n)"
    assert _render(fn("count", name("n"))) == "RETURN count(n)"


def test_forced_escaping_does_not_quote_function_names():
    renderer = Renderer.get(Configuration(server_version="5.26", always_escape_names=True))
    assert renderer.render(returning(count(asterisk()))).cypher == "RETURN count(*)"
    assert (
        renderer.render(returning(fn("point.distance", name("a"), name("b")))).cypher
        == "RETURN point.distance(`a`, `b`)"
    )


def test_forced_escaping_still_quotes_unusual_function_segments():
    renderer = Renderer.get(Configuration(server_version="5.26", always_escape_names=True))
    assert renderer.render(returning(fn("odd` name", name("a")))).cypher == "RETURN `odd`` name`(`a`)"


def test_sort_items_reject_aliased_expressions_at_construction():
    with pytest.raises(DslError, match="alias"):
        SortItem(name("x").alias("projected"), SortOrder.ASCENDING)


def test_count_renders_an_aggregate():
    assert _render(count(name("n"))) == "RETURN count(n)"
    assert _render(count(name("n"), distinct=True)) == "RETURN count(DISTINCT n)"


def test_count_asterisk_renders_the_star_argument():
    assert _render(count(asterisk())) == "RETURN count(*)"


def test_count_rejects_distinct_asterisk():
    with pytest.raises(DslError, match="DISTINCT"):
        count(asterisk(), distinct=True)


def test_asterisk_is_an_explicit_expression_node():
    star = asterisk()
    assert isinstance(star, Asterisk)
    assert _render(star) == "RETURN *"


def test_element_id_is_a_function_invocation():
    identifier = element_id(name("n"))
    assert isinstance(identifier, ElementId)
    assert isinstance(identifier, FunctionInvocation)
    assert _render(identifier) == "RETURN elementId(n)"


@pytest.mark.parametrize(
    ("server_version", "language"),
    [
        ("5.26", Language.AUTO),
        ("5.26", Language.NONE),
        ("5.26", Language.CYPHER_5),
        ("2026.10", Language.CYPHER_25),
        ("2025.01", Language.AUTO),
    ],
)
def test_element_id_renders_identically_on_every_supported_target(server_version, language):
    assert _render(element_id(name("n")), server_version, language).endswith("RETURN elementId(n)")


def test_element_id_accepts_expression_inputs():
    assert _render(element_id(name("entry")["uid"])) == "RETURN elementId(entry.uid)"


def test_element_id_is_not_a_rewritten_generic_function():
    assert _render(fn("elementId", name("n"))) == "RETURN elementId(n)"
    assert not isinstance(fn("elementId", name("n")), ElementId)


def test_sort_items_hold_a_direction_and_an_expression():
    ascending = asc(name("released"))
    descending = desc("released")
    assert isinstance(ascending, SortItem)
    assert ascending.direction is SortOrder.ASCENDING
    assert isinstance(ascending.expression, Variable)
    assert descending.direction is SortOrder.DESCENDING
    assert isinstance(descending.expression, Literal)


def test_sort_directions_have_their_cypher_values():
    assert SortOrder.ASCENDING.value == "ASC"
    assert SortOrder.DESCENDING.value == "DESC"


def test_raw_text_is_trusted_and_unrelated_to_parameters():
    trusted = raw("toString($value)")
    assert _render(trusted) == "RETURN toString($value)"
    rendered = Renderer.get(Configuration(server_version="5.26")).render(returning(trusted))
    assert rendered.parameters == {}
    assert rendered.unbound_parameters == frozenset()


@pytest.mark.parametrize("text", ["", "   "])
def test_raw_text_cannot_be_empty(text):
    with pytest.raises(DslError, match="raw"):
        raw(text)


def test_function_invocations_can_be_aliased():
    assert _render(fn("size", name("items")).alias("total")) == "RETURN size(items) AS total"


def test_aliased_expressions_are_not_function_arguments():
    with pytest.raises(DslError, match="alias"):
        fn("coalesce", name("a").alias("projected"))


def _render_forced_escaping(query):
    """
    Render with the Python equivalent of the pinned Java default configuration.

    Forced escaping also reaches variables and property keys here, unlike the pinned Java
    renderer, so the ported text carries extra backticks. The pinned expectation stays in
    a comment rather than being rewritten.
    """
    return Renderer.get(Configuration(server_version="5.26", always_escape_names=True)).render(query)


def test_upstream_count_in_the_return_clause():
    # Pinned: MATCH (u:`User`) RETURN count(u)
    user = node("User", name="u")
    assert _render_forced_escaping(match(user).returning(count(user))).cypher == (
        "MATCH (`u`:`User`) RETURN count(`u`)"
    )


def test_upstream_distinct_count_in_the_return_clause():
    # Pinned: MATCH (u:`User`) RETURN count(DISTINCT u)
    user = node("User", name="u")
    assert _render_forced_escaping(match(user).returning(count(user, distinct=True))).cypher == (
        "MATCH (`u`:`User`) RETURN count(DISTINCT `u`)"
    )


def test_upstream_aliased_count_in_the_return_clause():
    # Pinned: MATCH (u:`User`) RETURN count(u) AS cnt
    user = node("User", name="u")
    assert _render_forced_escaping(match(user).returning(count(user).alias("cnt"))).cypher == (
        "MATCH (`u`:`User`) RETURN count(`u`) AS `cnt`"
    )

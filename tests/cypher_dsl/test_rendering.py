# Ported from the Java Cypher-DSL test suite (neo4j/cypher-dsl, Apache-2.0).
# Traced sources: DefaultVisitorTests, PrettyPrintingVisitorTests, TemporalLiteralTests, IssueRelatedIT.
# Rewritten for pytest.
"""Rendering of return-only statements, prefixes and escapes."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import TZPATH, ZoneInfo

import pytest

from cypher_dsl import (
    AliasedExpression,
    AstNode,
    Configuration,
    Expression,
    Language,
    Literal,
    Renderer,
    Statement,
    StatementBuilder,
    SymbolicName,
    UnionStatement,
    lit,
    match,
    name,
    node,
    param,
    returning,
    union,
)
from cypher_dsl.errors import (
    ConflictingParameterError,
    DslError,
    InvalidClauseOrderError,
    InvalidIdentifierError,
    InvalidLiteralError,
    UnsupportedFeatureError,
)
from cypher_dsl.patterns.labels import ANY_LABEL, label
from cypher_dsl.render.literals import escape_string


@pytest.mark.parametrize("value", [None, False, 0, "", [], {}])
def test_falsey_values_are_bound(value):
    rendered = Renderer.get(Configuration(server_version="5.26")).render(returning(param("value", value)))
    assert rendered.parameters == {"value": value}
    assert rendered.unbound_parameters == frozenset()


def test_union_has_one_prefix():
    renderer = Renderer.get(Configuration(server_version="2026.10", language=Language.CYPHER_25))
    query = union(returning(lit(1).alias("x")), returning(lit(2).alias("x")))
    assert renderer.render(query).cypher == "CYPHER 25 RETURN 1 AS x UNION RETURN 2 AS x"


def test_boolean_and_integer_bindings_conflict():
    query = returning(param("value", True), param("value", 1))
    with pytest.raises(ConflictingParameterError):
        Renderer.get(Configuration(server_version="5.26")).render(query)


def test_cypher_25_is_not_supported_on_526():
    with pytest.raises(UnsupportedFeatureError):
        Renderer.get(Configuration(server_version="5.26", language=Language.CYPHER_25))


def test_default_configuration_renders_no_language_prefix():
    assert Renderer.get(Configuration(server_version="5.26")).render(returning(lit(1))).cypher == "RETURN 1"


def test_projection_bare_strings_are_variable_names():
    rendered = Renderer.get(Configuration(server_version="5.26")).render(returning("m"))
    assert rendered.cypher == "RETURN m"


def test_explicit_literal_string_stays_a_value():
    rendered = Renderer.get(Configuration(server_version="5.26")).render(returning(lit("m")))
    assert rendered.cypher == "RETURN 'm'"


def test_alias_is_rendered_as_a_projection_item():
    rendered = Renderer.get(Configuration(server_version="5.26")).render(returning(name("m").alias("movie")))
    assert rendered.cypher == "RETURN m AS movie"


def test_alias_with_spaces_is_quoted():
    rendered = Renderer.get(Configuration(server_version="5.26")).render(
        returning(name("n").alias("das ist ein Alias"))
    )
    assert rendered.cypher == "RETURN n AS `das ist ein Alias`"


def test_nested_alias_is_rejected_by_the_fluent_api():
    with pytest.raises(DslError, match="alias"):
        lit(1).alias("x").alias("y")


def test_nested_alias_nodes_cannot_be_constructed():
    inner = AliasedExpression(lit(1), SymbolicName("x"))
    with pytest.raises(DslError, match="alias"):
        AliasedExpression(inner, SymbolicName("y"))


def test_always_escape_names_applies_to_aliases_and_map_keys():
    renderer = Renderer.get(Configuration(server_version="5.26", always_escape_names=True))
    assert renderer.render(returning(lit({"a": 1}).alias("x"))).cypher == "RETURN {`a`: 1} AS `x`"


@pytest.mark.parametrize(
    ("server_version", "language", "expected_prefix"),
    [
        ("5.26", Language.AUTO, ""),
        ("5.26", Language.NONE, ""),
        ("5.26", Language.CYPHER_5, "CYPHER 5 "),
        ("2026.10", Language.CYPHER_25, "CYPHER 25 "),
        ("2025.01", Language.AUTO, ""),
    ],
)
def test_each_target_renders_its_language_prefix(server_version, language, expected_prefix):
    configuration = Configuration(server_version=server_version, language=language)
    rendered = Renderer.get(configuration).render(returning(lit(1).alias("x")))
    assert rendered.cypher == f"{expected_prefix}RETURN 1 AS x"


def test_union_all_uses_a_single_union_all_separator():
    rendered = Renderer.get(Configuration(server_version="5.26")).render(
        union(returning(lit(1).alias("x")), returning(lit(2).alias("x")), all=True)
    )
    assert rendered.cypher == "RETURN 1 AS x UNION ALL RETURN 2 AS x"


def test_union_accepts_a_built_statement_and_a_builder():
    statement = returning(lit(1).alias("x")).build()
    rendered = Renderer.get(Configuration(server_version="5.26")).render(union(statement, returning(lit(2).alias("x"))))
    assert rendered.cypher == "RETURN 1 AS x UNION RETURN 2 AS x"


def test_union_requires_at_least_two_parts():
    with pytest.raises(DslError):
        union(returning(lit(1).alias("x")))


def test_union_rejects_incompatible_known_projection_names():
    with pytest.raises(DslError, match="projection"):
        union(returning(lit(1).alias("x")), returning(lit(2).alias("y")))


def test_union_rejects_different_projection_counts():
    with pytest.raises(DslError, match="UNION branches"):
        union(returning(name("x"), name("y")), returning(name("x").alias("x")))


def test_union_allows_unknown_projection_names():
    rendered = Renderer.get(Configuration(server_version="5.26")).render(union(returning(lit(1)), returning(lit(2))))
    assert rendered.cypher == "RETURN 1 UNION RETURN 2"


def test_a_directly_constructed_union_needs_two_branches():
    with pytest.raises(DslError):
        UnionStatement((returning(lit(1)).build(),))


def test_a_directly_constructed_statement_with_two_returns_is_rejected():
    first = returning(lit(1).alias("x")).build()
    second = returning(lit(2).alias("y")).build()
    with pytest.raises(InvalidClauseOrderError):
        Statement(first.clauses + second.clauses)


def test_a_directly_constructed_statement_needs_a_clause():
    with pytest.raises(DslError):
        Statement(())


def test_a_directly_constructed_union_validates_projection_names():
    first = returning(lit(1).alias("x")).build()
    second = returning(lit(2).alias("y")).build()
    with pytest.raises(DslError, match="UNION projection"):
        UnionStatement((first, second))


def test_union_compares_known_names_across_an_unknown_first_branch():
    with pytest.raises(DslError, match="UNION projection"):
        union(returning(lit(0)), returning(lit(1).alias("x")), returning(lit(2).alias("y")))


def test_union_accepts_consistent_names_after_an_unknown_first_branch():
    rendered = Renderer.get(Configuration(server_version="5.26")).render(
        union(returning(lit(0)), returning(lit(1).alias("x")), returning(lit(2).alias("x")))
    )
    assert rendered.cypher == "RETURN 0 UNION RETURN 1 AS x UNION RETURN 2 AS x"


def test_returning_requires_at_least_one_expression():
    with pytest.raises(DslError):
        returning()


def test_build_rejects_an_incomplete_builder():
    with pytest.raises(DslError):
        StatementBuilder().build()


def test_rendering_rejects_an_incomplete_builder():
    with pytest.raises(DslError):
        Renderer.get(Configuration(server_version="5.26")).render(StatementBuilder())


def test_return_cannot_follow_return():
    with pytest.raises(InvalidClauseOrderError):
        returning(lit(1)).returning(lit(2))


def test_builder_and_statement_are_immutable():
    builder = returning(lit(1))
    statement = builder.build()
    with pytest.raises(FrozenInstanceError):
        builder.clauses = ()
    with pytest.raises(FrozenInstanceError):
        statement.clauses = ()


def test_a_builder_and_its_built_statement_render_identically():
    renderer = Renderer.get(Configuration(server_version="5.26"))
    builder = returning(param("p", 1), lit("x"))
    assert renderer.render(builder).cypher == renderer.render(builder.build()).cypher == "RETURN $p, 'x'"


def test_null_bool_int_and_float_render_in_type_order():
    rendered = Renderer.get(Configuration(server_version="5.26")).render(
        returning(lit(None), lit(False), lit(True), lit(0), lit(1), lit(1.5), lit(-2.25))
    )
    assert rendered.cypher == "RETURN null, false, true, 0, 1, 1.5, -2.25"


def test_strings_escape_backslashes_quotes_and_control_characters():
    assert escape_string("a\\b'c\"d\n\t\r\b\f") == r"'a\\b\'c\"d\n\t\r\b\f'"


def test_quoted_string_remains_a_single_value():
    rendered = Renderer.get(Configuration(server_version="5.26")).render(returning(lit("' RETURN 1 //")))
    assert rendered.cypher == r"RETURN '\' RETURN 1 //'"


def test_upstream_string_content_is_escaped():
    assert escape_string("A\\B\\\\Ca'bc123\\") == r"'A\\B\\\\Ca\'bc123\\'"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", "''"),
        (" \t ", r"' \t '"),
        ("Nothing to escape", "'Nothing to escape'"),
        ("' \" '", r"'\' \" \''"),
    ],
)
def test_upstream_strings_are_escaped(value, expected):
    assert escape_string(value) == expected


def test_inline_bytes_are_rejected_and_recommend_parameters():
    with pytest.raises(InvalidLiteralError, match="param"):
        Renderer.get(Configuration(server_version="5.26")).render(returning(lit(b"\x00\x01")))


def test_bound_bytes_remain_unchanged():
    rendered = Renderer.get(Configuration(server_version="5.26")).render(returning(param("data", b"\x00\x01")))
    assert rendered.cypher == "RETURN $data"
    assert rendered.parameters == {"data": b"\x00\x01"}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numeric_literals_are_rejected(value):
    with pytest.raises(InvalidLiteralError):
        Renderer.get(Configuration(server_version="5.26")).render(returning(Literal(value)))


def test_upstream_local_date_literal():
    assert Renderer.get(Configuration(server_version="5.26")).render(returning(lit(date(2021, 3, 10)))).cypher == (
        "RETURN date('2021-03-10')"
    )


def test_upstream_local_datetime_literal():
    assert Renderer.get(Configuration(server_version="5.26")).render(
        returning(lit(datetime(2021, 3, 10, 15, 13)))
    ).cypher == ("RETURN localdatetime('2021-03-10T15:13:00')")


def test_upstream_zoned_datetime_literal():
    value = datetime(2021, 3, 10, 15, 41, tzinfo=ZoneInfo("Europe/Berlin"))
    assert Renderer.get(Configuration(server_version="5.26")).render(returning(lit(value))).cypher == (
        "RETURN datetime('2021-03-10T15:41:00+01:00[Europe/Berlin]')"
    )


def test_upstream_local_time_literal():
    assert Renderer.get(Configuration(server_version="5.26")).render(returning(lit(time(15, 42)))).cypher == (
        "RETURN localtime('15:42:00')"
    )


def test_upstream_offset_time_literal():
    value = time(15, 15, tzinfo=timezone(timedelta(hours=2)))
    assert Renderer.get(Configuration(server_version="5.26")).render(returning(lit(value))).cypher == (
        "RETURN time('15:15:00+02:00')"
    )


def test_naive_time_is_local_and_aware_time_is_zoned():
    renderer = Renderer.get(Configuration(server_version="5.26"))
    naive = renderer.render(returning(lit(time(1, 2, 3, 4)))).cypher
    aware = renderer.render(returning(lit(time(1, 2, 3, 4, tzinfo=UTC)))).cypher
    assert naive == "RETURN localtime('01:02:03.000004')"
    assert aware == "RETURN time('01:02:03.000004+00:00')"


class _HostileZone(tzinfo):
    """A zone key carrying query syntax, as ZoneInfo.from_file permits."""

    key = "UTC]') AS x, 2 AS injected //"

    def utcoffset(self, value: datetime | None) -> timedelta:
        return timedelta(0)

    def dst(self, value: datetime | None) -> timedelta | None:
        return None

    def tzname(self, value: datetime | None) -> str:
        return "UTC"


def test_hostile_zone_key_is_rejected_from_a_custom_zone():
    value = datetime(2026, 1, 1, tzinfo=_HostileZone())
    with pytest.raises(InvalidLiteralError, match="Zone"):
        Renderer.get(Configuration(server_version="5.26")).render(returning(lit(value)))


def _system_zone_file() -> Path | None:
    for root in TZPATH:
        candidate = Path(root) / "UTC"
        if candidate.is_file():
            return candidate
    return None


@pytest.mark.skipif(_system_zone_file() is None, reason="The host has no system zoneinfo data.")
def test_hostile_zone_key_is_rejected_from_a_zoneinfo_value():
    zone_file = _system_zone_file()
    assert zone_file is not None
    with zone_file.open("rb") as stream:
        zone = ZoneInfo.from_file(stream, key="UTC]') AS x, 2 AS injected //")
    value = datetime(2026, 1, 1, tzinfo=zone)
    with pytest.raises(InvalidLiteralError, match="Zone"):
        Renderer.get(Configuration(server_version="5.26")).render(returning(lit(value)))


def test_a_valid_zone_key_renders_as_constructor_data():
    value = datetime(2021, 3, 10, 15, 41, tzinfo=ZoneInfo("Etc/GMT+5"))
    assert Renderer.get(Configuration(server_version="5.26")).render(returning(lit(value))).cypher == (
        "RETURN datetime('2021-03-10T15:41:00-05:00[Etc/GMT+5]')"
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (timedelta(days=1), "duration('PT24H')"),
        (timedelta(hours=1), "duration('PT1H')"),
        (timedelta(minutes=61), "duration('PT1H1M')"),
        (timedelta(seconds=61), "duration('PT1M1S')"),
        (timedelta(seconds=61, milliseconds=1123), "duration('PT1M2.123S')"),
        (timedelta(seconds=61, microseconds=1), "duration('PT1M1.000001S')"),
        (timedelta(hours=23, minutes=61, seconds=120), "duration('PT24H3M')"),
        (
            timedelta(days=364, hours=47, minutes=59, seconds=61, milliseconds=1001),
            "duration('PT8784H2.001S')",
        ),
    ],
)
def test_upstream_duration_literals(value, expected):
    assert (
        Renderer.get(Configuration(server_version="5.26")).render(returning(lit(value))).cypher == f"RETURN {expected}"
    )


def test_negative_durations_keep_a_single_sign_and_absolute_components():
    renderer = Renderer.get(Configuration(server_version="5.26"))
    assert renderer.render(returning(lit(timedelta(seconds=-1)))).cypher == "RETURN duration('-PT1S')"
    assert renderer.render(returning(lit(timedelta(hours=-1, minutes=-30)))).cypher == ("RETURN duration('-PT1H30M')")
    assert renderer.render(returning(lit(timedelta(0)))).cypher == "RETURN duration('PT0S')"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ALabel", "`ALabel`"),
        ("A Label", "`A Label`"),
        ("A `Label", "`A ``Label`"),
        ("`A `Label", "```A ``Label`"),
        ("Spring Data Neo4j⚡️RX", "`Spring Data Neo4j⚡️RX`"),
    ],
)
def test_upstream_names_are_always_escaped(raw, expected):
    renderer = Renderer.get(Configuration(server_version="5.26", always_escape_names=True))
    assert renderer.render(returning(name(raw))).cypher == f"RETURN {expected}"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ABC", "ABC"),
        ("A C", "`A C`"),
        ("A` C", "`A`` C`"),
        ("A`` C", "`A```` C`"),
        ("ALabel", "ALabel"),
        ("A `Label", "`A ``Label`"),
        ("`A `Label", "```A ``Label`"),
        ("Spring Data Neo4j⚡️RX", "`Spring Data Neo4j⚡️RX`"),
        ("Foo `", "`Foo ```"),
        ("`", "````"),
        ("```", "````````"),
        ("`a`b`c`", "```a``b``c```"),
    ],
)
def test_identifiers_quote_and_double_embedded_backticks(raw, expected):
    assert (
        Renderer.get(Configuration(server_version="5.26")).render(returning(name(raw))).cypher == f"RETURN {expected}"
    )


@pytest.mark.parametrize("raw", ["", "\x00", "\n", "a\nb", "a\x00b", "\x1f"])
def test_invalid_identifiers_are_rejected(raw):
    with pytest.raises(InvalidIdentifierError):
        Renderer.get(Configuration(server_version="5.26")).render(returning(name(raw)))


@pytest.mark.parametrize("raw", [r"x\u0060, 2 AS injected //", r"\u0060", r"x\U00000060y"])
def test_encoded_identifier_escapes_are_rejected(raw):
    with pytest.raises(InvalidIdentifierError, match="escape"):
        Renderer.get(Configuration(server_version="5.26")).render(returning(name(raw)))


@pytest.mark.parametrize("raw", [r"bad\u0000name", r"bad\u001fname"])
def test_encoded_control_characters_in_identifiers_are_rejected(raw):
    with pytest.raises(InvalidIdentifierError, match="control"):
        Renderer.get(Configuration(server_version="5.26")).render(returning(name(raw)))


def test_encoded_identifier_escapes_are_rejected_in_aliases():
    with pytest.raises(InvalidIdentifierError, match="escape"):
        Renderer.get(Configuration(server_version="5.26")).render(returning(lit(1).alias(r"x\u0060, 2 AS injected //")))


def test_encoded_identifier_escapes_are_rejected_in_map_keys():
    with pytest.raises(InvalidIdentifierError, match="escape"):
        Renderer.get(Configuration(server_version="5.26")).render(returning(lit({r"x\u0060": 1})))


@pytest.mark.parametrize("raw", ["true", "false", "null", "TRUE", "Null", "match", "and", "count"])
def test_reserved_names_render_as_quoted_variables(raw):
    assert Renderer.get(Configuration(server_version="5.26")).render(returning(name(raw))).cypher == f"RETURN `{raw}`"


def test_reserved_bare_strings_render_as_quoted_variables():
    assert Renderer.get(Configuration(server_version="5.26")).render(returning("true", "false", "null")).cypher == (
        "RETURN `true`, `false`, `null`"
    )


def test_reserved_alias_is_quoted():
    assert Renderer.get(Configuration(server_version="5.26")).render(returning(lit(1).alias("null"))).cypher == (
        "RETURN 1 AS `null`"
    )


def test_reserved_map_key_is_quoted():
    assert (
        Renderer.get(Configuration(server_version="5.26")).render(returning(lit({"true": 1}))).cypher
        == "RETURN {`true`: 1}"
    )


def test_invalid_alias_is_rejected_by_name():
    with pytest.raises(InvalidIdentifierError):
        Renderer.get(Configuration(server_version="5.26")).render(returning(name("n").alias("bad\nalias")))


def test_upstream_map_keys_are_quoted_when_needed():
    rendered = Renderer.get(Configuration(server_version="5.26")).render(
        returning(lit({"key 1": True, "key 2": False}))
    )
    assert rendered.cypher == "RETURN {`key 1`: true, `key 2`: false}"


def test_map_and_list_literals_preserve_structure_and_order():
    rendered = Renderer.get(Configuration(server_version="5.26")).render(
        returning(lit([1, "a", [True], {"b": None, "a": 2}]))
    )
    assert rendered.cypher == "RETURN [1, 'a', [true], {b: null, a: 2}]"


class _UnknownExpression(Expression):
    """Stand-in for an expression the renderer has no rule for."""


class _UnknownClause(AstNode):
    """Stand-in for a clause that statement validation does not accept."""


def test_unknown_expression_kinds_are_rejected_by_type_name():
    statement = returning(_UnknownExpression()).build()
    with pytest.raises(UnsupportedFeatureError, match="_UnknownExpression"):
        Renderer.get(Configuration(server_version="5.26")).render(statement)


def test_unknown_clause_kinds_are_rejected_at_statement_construction():
    with pytest.raises(DslError, match="RETURN"):
        Statement((_UnknownClause(),))


def test_repeated_rendering_is_stable_and_parameters_are_fresh():
    renderer = Renderer.get(Configuration(server_version="5.26"))
    statement = returning(param("p", 1), lit("x")).build()
    first = renderer.render(statement)
    second = renderer.render(statement)
    assert first.cypher == second.cypher == "RETURN $p, 'x'"
    assert first.parameters == second.parameters == {"p": 1}
    assert first.parameters is not second.parameters
    assert first.unbound_parameters is not second.unbound_parameters


def test_mutating_a_rendered_parameter_dictionary_does_not_affect_a_later_render():
    renderer = Renderer.get(Configuration(server_version="5.26"))
    statement = returning(param("p", 1)).build()
    first = renderer.render(statement)
    first.parameters["p"] = 99
    second = renderer.render(statement)
    assert second.parameters == {"p": 1}


def _render_match(pattern):
    statement = match(pattern).returning(lit(1))
    return Renderer.get(Configuration(server_version="5.26")).render(statement).cypher


@pytest.mark.parametrize(
    ("term", "label_text"),
    [
        # Manual, Label expressions: each operator and the grouping table.
        (label("A") & label("B"), "A&B"),
        (label("A") | label("B"), "A|B"),
        (~label("A"), "!A"),
        (~(~label("A")), "!!A"),
        (ANY_LABEL, "%"),
        (~ANY_LABEL, "!%"),
        (label("A") & (label("B") | label("C")), "A&(B|C)"),
        ((label("A") & label("B")) & ~(label("B") & label("C")), "A&B&!(B&C)"),
        (label("A") & (label("B") & label("C")), "A&(B&C)"),
        ((label("A") | label("B")) & ~label("C"), "(A|B)&!C"),
        (node("A").with_labels("B").label_expression, "A:B"),
    ],
)
def test_label_expression_term_rendering(term, label_text):
    # Source: Neo4j Cypher manual 5, Node and relationship patterns -> Label expressions.
    assert _render_match(node(term)) == f"MATCH (:{label_text}) RETURN 1"


@pytest.mark.parametrize(
    ("type_term", "type_text"),
    [
        # Manual, Label expressions: "the syntax for expressions matching a relationship
        # type is identical to that of label expressions".
        (label("R") | label("S"), "R|S"),
        (~label("R"), "!R"),
        (~label("R") & ~label("S"), "!R&!S"),
        (ANY_LABEL, "%"),
        ("R", "R"),
    ],
)
def test_type_expression_rendering(type_term, type_text):
    # Source: Neo4j Cypher manual 5, Node and relationship patterns -> Label expressions.
    chain = node("Person").relationship_to(node("Movie"), type_term)
    assert _render_match(chain) == f"MATCH (:Person)-[:{type_text}]->(:Movie) RETURN 1"


def test_label_expression_renders_one_line_in_pretty_mode():
    pattern = node(label("Movie") | label("Person"), name="n")
    statement = match(pattern).returning(pattern["title"])
    rendered = Renderer.get(Configuration(server_version="5.26", pretty_print=True)).render(statement)

    assert rendered.cypher == "MATCH (n:Movie|Person) RETURN n.title"


def test_a_label_expression_stays_inline_when_pretty_breaks_the_statement():
    pattern = node(label("Movie") | label("Person"), name="n")
    statement = match(pattern).returning(
        pattern["title"],
        pattern["released"],
        pattern["rating"],
        pattern["tagline"],
        pattern["runtime"],
        pattern["overview"],
        pattern["budget"],
        pattern["revenue"],
        pattern["homepage"],
        pattern["imdb_id"],
    )
    lines = Renderer.get(Configuration(server_version="5.26", pretty_print=True)).render(statement).cypher.splitlines()

    assert lines[0] == "MATCH (n:Movie|Person)"
    assert not any("Movie | Person" in line for line in lines)


def test_label_expression_escapes_names():
    pattern = node(label("A B") | label("C"))
    rendered = _render_match(pattern)

    assert "`A B`" in rendered


def test_label_expression_backticks_every_name_when_forced():
    pattern = node(label("A") & label("B"))
    rendered = (
        Renderer.get(Configuration(server_version="5.26", always_escape_names=True))
        .render(match(pattern).returning(lit(1)))
        .cypher
    )

    assert ":`A`&`B`" in rendered

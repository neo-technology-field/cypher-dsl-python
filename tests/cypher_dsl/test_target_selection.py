# Includes scenarios ported from the Java Cypher-DSL test suite (neo4j/cypher-dsl, Apache-2.0).
# Traced source: DialectIT. Rewritten for pytest.
"""Target selection: required release, language availability and requirement checks."""

from dataclasses import FrozenInstanceError

import pytest

from cypher_dsl import Configuration, Language, Renderer, assign, element_id, lit, match, name, node, param, returning
from cypher_dsl.errors import DslError, UnsupportedFeatureError
from cypher_dsl.features import Capability
from cypher_dsl.render.capabilities import ServerVersion
from cypher_dsl.render.targets import resolve_target
from cypher_dsl.statements.frames import SyntaxRequirement


def test_configuration_requires_a_release() -> None:
    with pytest.raises(TypeError, match="server_version"):
        Configuration()


def test_configuration_rejects_an_explicit_none_release() -> None:
    with pytest.raises(UnsupportedFeatureError, match="server_version is required"):
        Configuration(server_version=None)


@pytest.mark.parametrize("server_version", ["4.4", "5.0", "5.25"])
def test_releases_below_the_5_26_lts_are_refused(server_version) -> None:
    with pytest.raises(UnsupportedFeatureError, match=r"Neo4j releases before 5\.26 are not supported"):
        Configuration(server_version=server_version)


def test_language_availability_is_checked_at_construction() -> None:
    with pytest.raises(
        UnsupportedFeatureError,
        match=r"CYPHER 25 requires Neo4j 2025\.06 or later, but server_version is 5\.26",
    ):
        Configuration(server_version="5.26", language=Language.CYPHER_25)
    compatible = Configuration(server_version="5.26", language=Language.CYPHER_5)
    assert compatible.language is Language.CYPHER_5


def test_pinned_cypher_5_is_accepted_on_the_minimum() -> None:
    configuration = Configuration(server_version="5.26", language=Language.CYPHER_5)
    assert configuration.language is Language.CYPHER_5
    assert Renderer.get(configuration).render(returning(lit(1))).cypher == "CYPHER 5 RETURN 1"


def test_pinned_cypher_25_is_rejected_before_2025_06() -> None:
    with pytest.raises(UnsupportedFeatureError) as error:
        Configuration(server_version="2025.05", language=Language.CYPHER_25)
    assert (
        str(error.value)
        == """CYPHER 25 requires Neo4j 2025.06 or later, but server_version is 2025.05.
Select a compatible release or language."""
    )


def test_pinned_cypher_25_is_accepted_from_2025_06() -> None:
    configuration = Configuration(server_version="2025.06", language=Language.CYPHER_25)
    assert configuration.language is Language.CYPHER_25
    assert Renderer.get(configuration).render(returning(lit(1))).cypher == "CYPHER 25 RETURN 1"


def test_resolved_target_carries_release_language_and_one_rule_set() -> None:
    target = resolve_target(Configuration(server_version="2026.05.1"))
    assert target.release == ServerVersion.parse("2026.05.1")
    assert target.declared_version == "2026.05.1"
    assert target.language is Language.AUTO
    assert target.always_escape_names is False
    assert target.rules is resolve_target(Configuration(server_version="5.26")).rules


def test_automatic_language_adds_a_prefix_only_when_requirements_need_one() -> None:
    target = resolve_target(Configuration(server_version="2026.05.1"))
    assert target.effective_language(()) is None
    search = (SyntaxRequirement(Capability.VECTOR_SEARCH, (0, 0)),)
    assert target.effective_language(search) is Language.CYPHER_25
    pinned = resolve_target(Configuration(server_version="2026.05.1", language=Language.CYPHER_5))
    assert pinned.effective_language(search) is Language.CYPHER_5
    suppressed = resolve_target(Configuration(server_version="2026.05.1", language=Language.NONE))
    assert suppressed.effective_language(search) is None


def test_suppressed_prefix_renders_without_error() -> None:
    target = resolve_target(Configuration(server_version="2026.05.1", language=Language.NONE))
    search = (SyntaxRequirement(Capability.VECTOR_SEARCH, (0, 0)),)
    target.check_requirements(search)


def test_suppressed_prefix_still_rejects_an_incompatible_release() -> None:
    target = resolve_target(Configuration(server_version="2025.12", language=Language.NONE))
    search = (SyntaxRequirement(Capability.VECTOR_SEARCH, (0, 0)),)
    with pytest.raises(UnsupportedFeatureError) as error:
        target.check_requirements(search)
    assert (
        str(error.value)
        == """VECTOR_SEARCH requires Neo4j 2026.01 or later.
Target: server_version 2025.12.
Use a construct available on that release or declare a newer one."""
    )


def test_pinned_language_below_a_requirement_floor_fails() -> None:
    target = resolve_target(Configuration(server_version="2026.05.1", language=Language.CYPHER_5))
    search = (SyntaxRequirement(Capability.VECTOR_SEARCH, (0, 0)),)
    with pytest.raises(UnsupportedFeatureError) as error:
        target.check_requirements(search)
    assert (
        str(error.value)
        == """VECTOR_SEARCH requires Cypher 25, but language is set to CYPHER 5.
Omit language or select CYPHER 25."""
    )


@pytest.mark.parametrize("server_version", ["2025.12", "2025.12.0", "2025.12.1"])
def test_release_floors_are_checked_with_the_declared_spelling(server_version) -> None:
    target = resolve_target(Configuration(server_version=server_version))
    search = (SyntaxRequirement(Capability.VECTOR_SEARCH, (0, 0)),)
    with pytest.raises(UnsupportedFeatureError) as error:
        target.check_requirements(search)
    assert (
        str(error.value)
        == f"""VECTOR_SEARCH requires Neo4j 2026.01 or later.
Target: server_version {server_version}.
Use a construct available on that release or declare a newer one."""
    )


def test_plain_statements_render_unprefixed_and_pinned_statements_render_their_prefix() -> None:
    renderer = Renderer.get(Configuration(server_version="2026.05.1"))
    statement = returning(param("value", 1))
    assert renderer.render(statement).cypher == "RETURN $value"
    pinned = Renderer.get(Configuration(server_version="2026.05.1", language=Language.CYPHER_25))
    assert pinned.render(statement).cypher == "CYPHER 25 RETURN $value"


def test_dynamic_writes_render_on_a_compatible_release() -> None:
    record = node("Record", name="record")
    query = match(record).set_(assign(name("record")[param("key")], 1))
    renderer = Renderer.get(Configuration(server_version="5.26"))
    assert renderer.render(query).cypher == "MATCH (record:Record) SET record[$key] = 1"


def test_configuration_defaults_to_automatic_language_and_compact_unescaped_names() -> None:
    configuration = Configuration(server_version="5.26")
    assert configuration.language is Language.AUTO
    assert configuration.always_escape_names is False
    assert configuration.pretty_print is False
    assert configuration.server_target == ServerVersion(5, 26)


def test_configuration_is_frozen() -> None:
    configuration = Configuration(server_version="5.26")
    with pytest.raises(FrozenInstanceError):
        configuration.language = Language.CYPHER_5


def test_release_and_language_are_included_in_configuration_equality_and_hash() -> None:
    configuration = Configuration(server_version="5.26")
    same = Configuration(server_version="5.26", language=Language.AUTO)
    assert configuration == same
    assert hash(configuration) == hash(same)
    assert (
        len(
            {
                configuration,
                same,
                Configuration(server_version="2025.01"),
                Configuration(server_version="5.26", language=Language.CYPHER_5),
            }
        )
        == 3
    )


def test_malformed_server_version_fails_at_configuration_construction() -> None:
    with pytest.raises(DslError):
        Configuration(server_version="5.x")


def test_the_minimum_supported_release_renders_without_a_prefix() -> None:
    renderer = Renderer.get(Configuration(server_version="5.26"))
    assert renderer.render(returning(lit(1))).cypher == "RETURN 1"


def test_upstream_element_id_spelling_on_a_supported_release() -> None:
    pattern = node("Person", name="n")
    query = match(pattern).returning(element_id(pattern))
    renderer = Renderer.get(Configuration(server_version="5.26", always_escape_names=True))
    assert renderer.render(query).cypher == "MATCH (`n`:`Person`) RETURN elementId(`n`)"


def test_upstream_element_id_in_a_filter_and_a_projection() -> None:
    screen = node("ScreenStateNode", name="screen")
    identifier = lit("4:d32903f5-48ef-40fb-9ce5-9a3039852c46:2")
    query = match(screen).where(element_id(screen) == identifier).returning(element_id(screen))
    rendered = Renderer.get(Configuration(server_version="5.26", always_escape_names=True)).render(query)
    assert (
        rendered.cypher
        == """MATCH (`screen`:`ScreenStateNode`) WHERE elementId(`screen`) = \
'4:d32903f5-48ef-40fb-9ce5-9a3039852c46:2' RETURN elementId(`screen`)"""
    )

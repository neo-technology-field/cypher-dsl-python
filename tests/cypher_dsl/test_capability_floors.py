# Includes scenarios ported from the Java Cypher-DSL test suite (neo4j/cypher-dsl, Apache-2.0).
# Traced source: DialectIT. Rewritten for pytest.
"""Capability floors: the language and release each syntax family requires."""

import pytest

from cypher_dsl.errors import DslError
from cypher_dsl.features import Capability, Language
from cypher_dsl.render.capabilities import (
    CYPHER_25_MINIMUM,
    SUPPORTED_RELEASE_MINIMUM,
    CapabilityFloor,
    ServerVersion,
    capability_available,
    floor_for,
)

# An independent copy of the table, so a wrong floor or a missing row fails here
# rather than passing a lookup against the implementation.
EXPECTED_FLOORS = {
    Capability.SCOPE_CLAUSES: CapabilityFloor(None, ServerVersion(5, 23)),
    Capability.OPTIONAL_CALL: CapabilityFloor(None, ServerVersion(5, 24)),
    Capability.IN_TRANSACTIONS: CapabilityFloor(None, ServerVersion(4, 4)),
    Capability.DYNAMIC_PROPERTY_WRITES: CapabilityFloor(None, ServerVersion(5, 24)),
    Capability.DYNAMIC_LABELS: CapabilityFloor(None, ServerVersion(5, 26)),
    Capability.VECTOR_SEARCH: CapabilityFloor(Language.CYPHER_25, ServerVersion(2026, 1)),
    Capability.FULLTEXT_SEARCH: CapabilityFloor(Language.CYPHER_25, ServerVersion(2026, 9)),
}


def test_every_capability_has_one_floor_row() -> None:
    assert {capability: floor_for(capability) for capability in Capability} == EXPECTED_FLOORS


def test_floors_compare_across_the_calendar_boundary() -> None:
    assert capability_available(Capability.DYNAMIC_LABELS, ServerVersion.parse("5.25")) is False
    assert capability_available(Capability.DYNAMIC_LABELS, ServerVersion.parse("5.26")) is True
    assert capability_available(Capability.DYNAMIC_LABELS, ServerVersion.parse("2025.01")) is True


def test_fulltext_search_floor_is_2026_09() -> None:
    assert capability_available(Capability.FULLTEXT_SEARCH, ServerVersion.parse("2026.08")) is False
    assert capability_available(Capability.FULLTEXT_SEARCH, ServerVersion.parse("2026.09")) is True


def test_language_and_support_floors() -> None:
    assert ServerVersion(5, 26) == SUPPORTED_RELEASE_MINIMUM
    assert ServerVersion(2025, 6) == CYPHER_25_MINIMUM
    assert capability_available(Capability.VECTOR_SEARCH, ServerVersion.parse("2026.01")) is True
    assert capability_available(Capability.VECTOR_SEARCH, ServerVersion.parse("2025.06")) is False


def test_support_and_language_floors_land_on_the_documenting_release() -> None:
    assert ServerVersion.parse("5.25") < SUPPORTED_RELEASE_MINIMUM
    assert ServerVersion.parse("5.26") == SUPPORTED_RELEASE_MINIMUM
    assert ServerVersion.parse("2025.05") < CYPHER_25_MINIMUM
    assert ServerVersion.parse("2025.06") == CYPHER_25_MINIMUM
    assert ServerVersion.parse("2025.01") > SUPPORTED_RELEASE_MINIMUM


def test_every_language_floor_is_parseable_at_its_capability_release_floor() -> None:
    availability = {Language.CYPHER_25: CYPHER_25_MINIMUM}
    for capability in Capability:
        floor = floor_for(capability)
        if floor.language is not None:
            assert floor.release >= availability[floor.language]


@pytest.mark.parametrize(
    ("capability", "server", "expected"),
    [
        (Capability.SCOPE_CLAUSES, "5.0", False),
        (Capability.SCOPE_CLAUSES, "5.22", False),
        (Capability.SCOPE_CLAUSES, "5.23", True),
        (Capability.SCOPE_CLAUSES, "5.26", True),
        (Capability.SCOPE_CLAUSES, "2025.01", True),
        (Capability.OPTIONAL_CALL, "5.23", False),
        (Capability.OPTIONAL_CALL, "5.24", True),
        (Capability.OPTIONAL_CALL, "5.26", True),
        (Capability.OPTIONAL_CALL, "2025.01", True),
        (Capability.IN_TRANSACTIONS, "4.3", False),
        (Capability.IN_TRANSACTIONS, "4.4", True),
        (Capability.IN_TRANSACTIONS, "5.26", True),
        (Capability.IN_TRANSACTIONS, "2025.01", True),
        (Capability.DYNAMIC_PROPERTY_WRITES, "5.23", False),
        (Capability.DYNAMIC_PROPERTY_WRITES, "5.24", True),
        (Capability.DYNAMIC_PROPERTY_WRITES, "5.26", True),
        (Capability.DYNAMIC_PROPERTY_WRITES, "2025.01", True),
        (Capability.DYNAMIC_LABELS, "5.0", False),
        (Capability.DYNAMIC_LABELS, "5.23", False),
        (Capability.DYNAMIC_LABELS, "5.25", False),
        (Capability.DYNAMIC_LABELS, "5.26", True),
        (Capability.DYNAMIC_LABELS, "2025.01", True),
        (Capability.VECTOR_SEARCH, "2025.10", False),
        (Capability.VECTOR_SEARCH, "2025.12", False),
        (Capability.VECTOR_SEARCH, "2026.01", True),
        (Capability.VECTOR_SEARCH, "2026.10", True),
        (Capability.FULLTEXT_SEARCH, "2026.08", False),
        (Capability.FULLTEXT_SEARCH, "2026.09", True),
        (Capability.FULLTEXT_SEARCH, "2026.10", True),
    ],
)
def test_capability_floors_follow_the_declared_release(capability, server, expected) -> None:
    assert capability_available(capability, ServerVersion.parse(server)) is expected


def test_server_version_is_parsed_into_integer_components() -> None:
    version = ServerVersion.parse("2026.10")
    assert (version.major, version.minor, version.patch) == (2026, 10, 0)
    assert str(version) == "2026.10"
    assert str(ServerVersion.parse("2025.06")) == "2025.06"
    assert ServerVersion.parse("5.26.1") == ServerVersion(5, 26, 1)


def test_server_versions_order_numerically() -> None:
    assert ServerVersion.parse("5.26") > ServerVersion.parse("5.9")
    assert ServerVersion.parse("2026.10") > ServerVersion.parse("2026.9")
    assert ServerVersion.parse("2026.01") == ServerVersion.parse("2026.1")


@pytest.mark.parametrize("raw", ["", "5", "5.x", "-1.2", "5.26.1.2", "5. 26", " 5.26"])
def test_malformed_server_versions_are_rejected(raw) -> None:
    with pytest.raises(DslError):
        ServerVersion.parse(raw)

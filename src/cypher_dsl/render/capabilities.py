"""
Declared-server capability checks for syntax that is not in every language or release.

A capability floor names the language and release that first parse a syntax family. The
declared release and the language selection are the only inputs. Nothing here contacts a
server: the caller states the target, the library checks it once and the renderer refuses
syntax the target cannot parse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from cypher_dsl.errors import DslError, UnsupportedFeatureError
from cypher_dsl.features import Capability, Language

_VERSION_PATTERN: Final = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


@dataclass(frozen=True, order=True, weakref_slot=True, slots=True)
class ServerVersion:
    """
    A Neo4j release parsed into comparable integer components.

    Ordering is numeric, so ``5.26`` is newer than ``5.9``. Comparing the original
    strings would put ``5.9`` later, and parsing through floats would lose the patch
    component and risk rounding mistakes.

    Attributes:
        major: Year-based or legacy major component.
        minor: Release within the major component.
        patch: Optional patch component, zero when the caller omits it.
    """

    major: int
    minor: int
    patch: int = 0

    def __str__(self) -> str:
        """Return the declared form, using the two-digit minor that calendar versions use."""
        major_minor = f"{self.major}.{self.minor:02d}" if self.major >= 2000 else f"{self.major}.{self.minor}"
        if self.patch:
            return f"{major_minor}.{self.patch}"
        return major_minor

    @classmethod
    def parse(cls, raw: str) -> ServerVersion:
        """
        Parse a declared release string such as ``"5.26"`` or ``"2026.10"``.

        Args:
            raw: Release string with two or three dot-separated integer components.

        Returns:
            A comparable version value.

        Raises:
            DslError: If the string does not have two or three unsigned integer
                components. Surrounding whitespace is rejected rather than trimmed,
                because a declared target should be stated exactly.
        """
        match = _VERSION_PATTERN.fullmatch(raw)
        if match is None:
            raise DslError(f"Invalid server version {raw!r}. Declare it as '5.26', '2026.10' or '2026.10.1'.")
        major, minor, patch = match.groups()
        return cls(int(major), int(minor), 0 if patch is None else int(patch))


# 5.26 is the final 5.x release and the LTS, hotfix-supported until June 2028. Every
# calendar release from 2025.01 compares above it numerically, so one floor covers the
# whole supported range.
SUPPORTED_RELEASE_MINIMUM: Final = ServerVersion(5, 26)
# CYPHER 5 selection arrived in Neo4j 5.21 and the tagged 5.21 parser test accepts
# "CYPHER 5 RETURN 42" (community/cypher/cypher/src/test/scala/.../PreParserTest.scala).
# That release is below the supported minimum, so every supported target accepts the
# prefix and only CYPHER 25 needs a floor. CYPHER 25 arrived with versioning in 2025.06.
# Sources:
# https://neo4j.com/docs/cypher-manual/current/deprecations-additions-removals-compatibility/
# https://neo4j.com/docs/cypher-manual/current/queries/select-version/
CYPHER_25_MINIMUM = ServerVersion(2025, 6)
VECTOR_SEARCH_MINIMUM = ServerVersion(2026, 1)
FULLTEXT_SEARCH_MINIMUM = ServerVersion(2026, 9)
# The variable scope clause arrived in 5.23:
# https://neo4j.com/docs/cypher-manual/5/deprecations-additions-removals-compatibility/#cypher-deprecations-additions-removals-5.23
SCOPE_CLAUSES_MINIMUM = ServerVersion(5, 23)
# OPTIONAL CALL requires 5.24:
# https://neo4j.com/docs/cypher-manual/5/subqueries/call-subquery/#optional-subquery-calls
OPTIONAL_CALL_MINIMUM = ServerVersion(5, 24)
# Inner transactions for CALL subqueries require 4.4:
# https://neo4j.com/docs/cypher-manual/4.4/deprecations-additions-removals-compatibility/#cypher-deprecations-additions-removals-4.4
IN_TRANSACTIONS_MINIMUM = ServerVersion(4, 4)
# Dynamic labels and types arrived in 5.26:
# https://neo4j.com/docs/cypher-manual/5/clauses/create/
DYNAMIC_LABELS_MINIMUM = ServerVersion(5, 26)
DYNAMIC_PROPERTY_WRITES_MINIMUM = ServerVersion(5, 24)

# CYPHER 25 is the only selectable language whose availability floor is above the
# supported minimum. One table owns that rule for construction and for resolution.
_LANGUAGE_FLOORS: Final = {
    Language.CYPHER_25: CYPHER_25_MINIMUM,
}

_LANGUAGE_NAMES: Final = {
    Language.AUTO: "AUTO",
    Language.NONE: "NONE",
    Language.CYPHER_5: "CYPHER 5",
    Language.CYPHER_25: "CYPHER 25",
}


def language_name(language: Language) -> str:
    """Return the spelling a language prefix or diagnostic uses for one selection."""
    return _LANGUAGE_NAMES[language]


def validate_language(language: Language, release: ServerVersion, declared: str) -> None:
    """
    Reject a language selection the declared release cannot parse.

    Args:
        language: Language selected in the configuration.
        release: Parsed declared release.
        declared: Release string as the caller wrote it, used in the diagnostic.

    Raises:
        UnsupportedFeatureError: If the selection has a floor above the declared
            release. ``AUTO`` and ``NONE`` emit no prefix of their own and have no
            floor.
    """
    floor = _LANGUAGE_FLOORS.get(language)
    if floor is not None and release < floor:
        raise UnsupportedFeatureError(
            f"""{language_name(language)} requires Neo4j {floor} or later, but server_version is {declared}.
Select a compatible release or language."""
        )


@dataclass(frozen=True, weakref_slot=True, slots=True)
class CapabilityFloor:
    """The language and release a capability needs from a declared target."""

    language: Language | None
    release: ServerVersion


_CAPABILITY_FLOORS: Final = {
    Capability.SCOPE_CLAUSES: CapabilityFloor(None, SCOPE_CLAUSES_MINIMUM),
    Capability.OPTIONAL_CALL: CapabilityFloor(None, OPTIONAL_CALL_MINIMUM),
    Capability.IN_TRANSACTIONS: CapabilityFloor(None, IN_TRANSACTIONS_MINIMUM),
    Capability.DYNAMIC_PROPERTY_WRITES: CapabilityFloor(None, DYNAMIC_PROPERTY_WRITES_MINIMUM),
    Capability.DYNAMIC_LABELS: CapabilityFloor(None, DYNAMIC_LABELS_MINIMUM),
    Capability.VECTOR_SEARCH: CapabilityFloor(Language.CYPHER_25, VECTOR_SEARCH_MINIMUM),
    Capability.FULLTEXT_SEARCH: CapabilityFloor(Language.CYPHER_25, FULLTEXT_SEARCH_MINIMUM),
}


def floor_for(capability: Capability) -> CapabilityFloor:
    """Return the language and release floors one capability needs."""
    floor = _CAPABILITY_FLOORS.get(capability)
    if floor is None:
        raise UnsupportedFeatureError(f"Capability {capability.value} has no resolution rule.")
    return floor


def capability_available(capability: Capability, release: ServerVersion) -> bool:
    """Return whether a declared release meets a capability's release floor."""
    return release >= floor_for(capability).release


__all__ = [
    "CYPHER_25_MINIMUM",
    "DYNAMIC_LABELS_MINIMUM",
    "DYNAMIC_PROPERTY_WRITES_MINIMUM",
    "FULLTEXT_SEARCH_MINIMUM",
    "IN_TRANSACTIONS_MINIMUM",
    "OPTIONAL_CALL_MINIMUM",
    "SCOPE_CLAUSES_MINIMUM",
    "SUPPORTED_RELEASE_MINIMUM",
    "VECTOR_SEARCH_MINIMUM",
    "Capability",
    "CapabilityFloor",
    "ServerVersion",
    "capability_available",
    "floor_for",
    "language_name",
    "validate_language",
]

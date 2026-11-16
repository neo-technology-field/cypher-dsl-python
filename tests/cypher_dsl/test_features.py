"""Language levels and capability identities."""

from cypher_dsl.features import Capability, Language


def test_language_levels_are_distinct_identities() -> None:
    assert {member.name for member in Language} == {"AUTO", "NONE", "CYPHER_5", "CYPHER_25"}
    assert Language.AUTO.value == "AUTO"
    assert Language.NONE.value == "NONE"
    assert Language.CYPHER_5.value == "CYPHER_5"
    assert Language.CYPHER_25.value == "CYPHER_25"


def test_capability_identities_are_unchanged() -> None:
    assert {member.name for member in Capability} == {
        "SCOPE_CLAUSES",
        "DYNAMIC_LABELS",
        "DYNAMIC_PROPERTY_WRITES",
        "VECTOR_SEARCH",
        "FULLTEXT_SEARCH",
    }

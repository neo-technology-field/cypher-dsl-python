"""Target-independent syntax identities: language levels and capabilities."""

from enum import Enum


class Capability(Enum):
    """A syntax family whose availability depends on target and release."""

    SCOPE_CLAUSES = "SCOPE_CLAUSES"
    OPTIONAL_CALL = "OPTIONAL_CALL"
    IN_TRANSACTIONS = "IN_TRANSACTIONS"
    DYNAMIC_LABELS = "DYNAMIC_LABELS"
    DYNAMIC_PROPERTY_WRITES = "DYNAMIC_PROPERTY_WRITES"
    VECTOR_SEARCH = "VECTOR_SEARCH"
    FULLTEXT_SEARCH = "FULLTEXT_SEARCH"
    IS_LABELED = "IS_LABELED"


class Language(Enum):
    """How the rendered text names, selects or omits its Cypher language."""

    AUTO = "AUTO"
    NONE = "NONE"
    CYPHER_5 = "CYPHER_5"
    CYPHER_25 = "CYPHER_25"


__all__ = ["Capability", "Language"]

"""
Construction and rendering failures raised by the DSL.

Every error derives from ``DslError`` so that callers can catch the library's own
failures without catching unrelated Python exceptions. Messages name the construct
that failed and, where the choice exists, the supported alternative.
"""


class DslError(Exception):
    """Base class for every construction and rendering failure."""


class UnsupportedFeatureError(DslError):
    """Raised when a requested construct is outside the implemented surface."""


class InvalidClauseOrderError(DslError):
    """Raised when clauses form a sequence that Cypher does not accept."""


class ConflictingParameterError(DslError):
    """Raised when one parameter name carries two different bindings."""


class InvalidIdentifierError(DslError):
    """Raised when a name cannot be rendered as a quoted identifier."""


class EmptyPatternError(DslError):
    """Raised when a grammar position requires at least one pattern or item."""


class InvalidLiteralError(DslError):
    """Raised when a Python value cannot be represented as a frozen literal."""

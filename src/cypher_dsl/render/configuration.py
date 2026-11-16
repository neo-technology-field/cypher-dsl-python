"""
Immutable rendering configuration.

The configuration is a value object: two configurations with the same settings are
interchangeable, and a renderer never changes one. Options that are not implemented fail
here rather than being accepted and ignored, because a silently ignored option produces
output the caller did not ask for.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cypher_dsl.errors import UnsupportedFeatureError
from cypher_dsl.features import Language
from cypher_dsl.render.capabilities import SUPPORTED_RELEASE_MINIMUM, ServerVersion, validate_language


@dataclass(frozen=True, weakref_slot=True, slots=True)
class Configuration:
    """
    Settings that select the target and quoting for one or more renders.

    Attributes:
        server_version: Declared Neo4j release the rendered text will run on. The library
            never contacts a server to discover it.
        language: How the text names its Cypher language. ``AUTO`` emits a prefix only
            when the statement's requirements need one, ``NONE`` never emits one, and a
            pinned value always emits it.
        always_escape_names: Quote every identifier, including names that would be
            legal unquoted.
        pretty_print: Not implemented. Setting it is an explicit failure, not a request
            that is quietly dropped.
        server_target: Parsed form of ``server_version``, derived once at construction
            and excluded from equality because it carries no separate information.

    Raises:
        UnsupportedFeatureError: If ``server_version`` is not a string, pretty printing
            is requested before it exists, the declared release is below 5.26, or the
            selected language is not parseable on the declared release.
        DslError: If ``server_version`` cannot be parsed.
    """

    server_version: str
    language: Language = Language.AUTO
    always_escape_names: bool = False
    pretty_print: bool = False
    server_target: ServerVersion = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        """Validate the options that cannot be honoured or parsed."""
        if self.pretty_print:
            raise UnsupportedFeatureError(
                """Pretty printing is not implemented.
Use pretty_print=False and format the compact output outside the library."""
            )
        if not isinstance(self.server_version, str):
            raise UnsupportedFeatureError(
                """server_version is required.
Declare the Neo4j release the rendered text will run on, such as '5.26' or '2026.10'."""
            )
        target = ServerVersion.parse(self.server_version)
        if target < SUPPORTED_RELEASE_MINIMUM:
            raise UnsupportedFeatureError(
                f"""Neo4j releases before 5.26 are not supported.
Declare the 5.26 LTS or a later release, such as '5.26' or '2026.10', not {self.server_version!r}."""
            )
        object.__setattr__(self, "server_target", target)
        validate_language(self.language, target, self.server_version)


__all__ = ["Configuration"]

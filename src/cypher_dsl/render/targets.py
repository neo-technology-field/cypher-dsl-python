"""One resolved target per renderer: a declared release, a language selection and the rules."""

from __future__ import annotations

from dataclasses import dataclass

from cypher_dsl.errors import UnsupportedFeatureError
from cypher_dsl.features import Language
from cypher_dsl.render.capabilities import (
    ServerVersion,
    capability_available,
    floor_for,
    language_name,
    validate_language,
)
from cypher_dsl.render.configuration import Configuration
from cypher_dsl.render.rules import RenderingRules
from cypher_dsl.render.statements import shared_bindings
from cypher_dsl.statements.analysis import SyntaxRequirement


@dataclass(frozen=True, weakref_slot=True, slots=True)
class ResolvedTarget:
    """The declared release, language selection and rules one renderer uses."""

    release: ServerVersion
    declared_version: str
    language: Language
    always_escape_names: bool
    rules: RenderingRules

    def effective_language(self, requirements: tuple[SyntaxRequirement, ...]) -> Language | None:
        """Return the language the text names, or ``None`` when it emits no prefix."""
        if self.language is Language.NONE:
            return None
        if self.language is not Language.AUTO:
            return self.language
        needed = [floor_for(item.capability).language for item in requirements]
        if Language.CYPHER_25 in needed:
            return Language.CYPHER_25
        if Language.CYPHER_5 in needed:
            return Language.CYPHER_5
        return None

    def check_requirements(self, requirements: tuple[SyntaxRequirement, ...]) -> None:
        """Reject required syntax the declared release or selected language cannot parse."""
        for requirement in requirements:
            capability = requirement.capability
            floor = floor_for(capability)
            if not capability_available(capability, self.release):
                raise UnsupportedFeatureError(
                    f"""{capability.value} requires Neo4j {floor.release} or later.
Target: server_version {self.declared_version}.
Use a construct available on that release or declare a newer one."""
                )
            if (
                floor.language is not None
                and self.language not in (Language.AUTO, Language.NONE)
                and self.language is not floor.language
            ):
                raise UnsupportedFeatureError(
                    f"""{capability.value} requires Cypher 25, but language is set to {language_name(self.language)}.
Omit language or select CYPHER 25."""
                )

    def language_prefix(self, requirements: tuple[SyntaxRequirement, ...]) -> str:
        """Return the language prefix for one render, empty when none is emitted."""
        effective = self.effective_language(requirements)
        if effective is None:
            return ""
        return f"{language_name(effective)} "


_RULES = RenderingRules.from_bindings(shared_bindings())


def resolve_target(configuration: Configuration) -> ResolvedTarget:
    """Resolve and validate one target when a renderer is constructed."""
    validate_language(configuration.language, configuration.server_target, configuration.server_version)
    return ResolvedTarget(
        release=configuration.server_target,
        declared_version=configuration.server_version,
        language=configuration.language,
        always_escape_names=configuration.always_escape_names,
        rules=_RULES,
    )


__all__ = ["ResolvedTarget", "resolve_target"]

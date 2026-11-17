"""
Renderer facade and the ``Rendered`` result it returns.

A renderer is a stateless facade over an immutable configuration. Every call creates a
fresh analysis, traversal and binding collector, so repeated renders and concurrent
renders cannot see each other's state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from cypher_dsl.errors import UnsupportedFeatureError
from cypher_dsl.render.bindings import BindingCollector
from cypher_dsl.render.configuration import Configuration
from cypher_dsl.render.pretty import render_pretty
from cypher_dsl.render.targets import resolve_target
from cypher_dsl.render.traversal import RenderingTraversal
from cypher_dsl.statements.analysis import analyse
from cypher_dsl.statements.builder import StatementBuilder
from cypher_dsl.statements.composition import Statement, UnionStatement

RenderInput: TypeAlias = Statement | StatementBuilder | UnionStatement


@dataclass(frozen=True, weakref_slot=True, slots=True)
class Rendered:
    """
    One render result: query text and the bindings that belong to that text.

    Attributes:
        cypher: Complete query text, including any language prefix.
        parameters: Fresh dictionary of bound values. Mutating it does not affect the
            syntax tree or another result.
        unbound_parameters: Names the caller must supply at execution time.
    """

    cypher: str
    parameters: dict[str, object]
    unbound_parameters: frozenset[str]

    def __str__(self) -> str:
        """Return the query text, so printing a result needs no attribute access."""
        return self.cypher


class Renderer:
    """
    Renders statements and construction values under one configuration.

    Instances hold no traversal state. The same renderer can be stored globally and used
    from several threads.
    """

    __slots__ = ("_configuration", "_target")

    def __init__(self, configuration: Configuration) -> None:
        """Validate and store one immutable resolved target."""
        self._configuration = configuration
        self._target = resolve_target(configuration)

    @classmethod
    def get(cls, configuration: Configuration) -> Renderer:
        """
        Return a renderer for a configuration, validating the declared target.

        Args:
            configuration: Immutable settings for subsequent renders.

        Returns:
            A renderer that can be shared or stored.

        Raises:
            UnsupportedFeatureError: If the configuration's language selection is not
                available on its declared release.
        """
        return cls(configuration)

    def render(self, statement: RenderInput) -> Rendered:
        """
        Render one statement builder or finalised statement.

        Finalise, analyse in one validating walk, check requirements, collect bindings, then render.
        Analysis and rendering make two tree walks over the finalised AST.

        Args:
            statement: Construction value, finalised statement or union. Statement
                builders are finalised through ``build`` before rendering.

        Returns:
            A ``Rendered`` with query text and fresh parameter containers.

        Raises:
            UnsupportedFeatureError: If the input or a node kind has no rendering rule.
            DslError: If the input is incomplete or its bindings conflict.
        """
        finalised = _finalise(statement)
        analysis = analyse(finalised)
        self._target.check_requirements(analysis.requirements)
        bindings = BindingCollector()
        for parameter in analysis.parameters:
            bindings.record(parameter.symbol.value, parameter.binding)
        if self._target.pretty_print:
            body = render_pretty(finalised, analysis, self._target.always_escape_names, self._target.rules)
        else:
            traversal = RenderingTraversal(
                self._target.rules, analysis, self._target.always_escape_names, self._target.layout
            )
            body = traversal.render(finalised)
        language_prefix = self._target.language_prefix(analysis.requirements)
        if language_prefix and self._target.pretty_print:
            cypher = f"{language_prefix.rstrip()}\n{body}"
        else:
            cypher = language_prefix + body
        return Rendered(
            cypher=cypher,
            parameters=bindings.parameters,
            unbound_parameters=bindings.unbound_parameters,
        )


def _finalise(value: object) -> Statement | UnionStatement:
    if isinstance(value, StatementBuilder):
        return value.build()
    if isinstance(value, (Statement, UnionStatement)):
        return value
    raise UnsupportedFeatureError(f"Rendering is not implemented for {type(value).__name__}.")


__all__ = ["RenderInput", "Rendered", "Renderer"]

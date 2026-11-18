"""Semantic rules for label expression predicates."""

from __future__ import annotations

from cypher_dsl.expressions.labels import IsLabeled
from cypher_dsl.features import Capability
from cypher_dsl.statements.frames import ScopeFrame
from cypher_dsl.statements.rules.base import AnalysisSink, SemanticRule


class IsLabeledRule(SemanticRule[IsLabeled]):
    """Record the language and release floor an ``IS [NOT] LABELED`` predicate needs."""

    __slots__ = ()

    def record(self, node: IsLabeled, frame: ScopeFrame, sink: AnalysisSink) -> None:
        """Require the ``IS_LABELED`` capability for this occurrence."""
        sink.requirement(Capability.IS_LABELED)

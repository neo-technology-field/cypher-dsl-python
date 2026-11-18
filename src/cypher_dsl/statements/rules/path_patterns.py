"""The path pattern rule: every name the chain carries must already be visible."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cypher_dsl.errors import DslError
from cypher_dsl.expressions.path_patterns import PathPatternExpression
from cypher_dsl.patterns.nodes import NodePattern
from cypher_dsl.statements.frames import DeclarationRole, ScopeFrame, reference_names
from cypher_dsl.statements.rules.base import SemanticRule
from cypher_dsl.statements.rules.patterns import pattern_bindings

if TYPE_CHECKING:
    from cypher_dsl.statements.rules.base import PatternState


class PathPatternRule(SemanticRule[PathPatternExpression]):
    """Check the chain's names against the frame the enclosing expression position reads."""

    __slots__ = ()

    def validate(self, node: PathPatternExpression, frame: ScopeFrame) -> None:
        """
        Reject a chain name the available frame does not contain.

        The chain references names an earlier clause binds and declares none of its
        own. The check follows the shared closed-frame rule: an open frame cannot
        prove a name missing, so a reference there is tolerated and left to the
        server.
        """
        names = reference_names(frame)
        if names is None:
            return
        for bound in pattern_bindings((node.pattern,)):
            if bound not in names:
                raise DslError(
                    f"The path pattern expression refers to {bound!r}, which is not in scope. "
                    "A path pattern expression references names earlier clauses bind. "
                    "Use exists() for a pattern that binds its own names."
                )

    def pattern_role(
        self, clause: PathPatternExpression, node_pattern: NodePattern, frame: ScopeFrame, state: PatternState
    ) -> DeclarationRole | None:
        """Declare every node occurrence inside the chain, so it renders with its labels."""
        return DeclarationRole.DECLARE


__all__ = ["PathPatternRule"]

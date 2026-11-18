"""
The path pattern expression.

A relationship chain used as a boolean reads the enclosing scope: it references names
earlier clauses bind and declares none of its own. That is the difference from
``EXISTS``, whose body may bind its own names, and it is what keeps the expression
valid only where Cypher expects a boolean.
"""

from __future__ import annotations

from dataclasses import dataclass

from cypher_dsl.ast import AstNode
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.operators import Condition
from cypher_dsl.patterns.nodes import NodePattern
from cypher_dsl.patterns.relationships import RelationshipPattern


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class PathPatternExpression(Condition):
    """
    Test whether a relationship chain matches at least once, as a boolean.

    The value is a predicate, so the expression filters in ``WHERE`` and combines
    with ``&``, ``|`` and ``~``. Every named node and relationship inside the chain
    references a name an earlier clause binds; the expression declares no names of
    its own, and a projection item is not a boolean position for it.

    Attributes:
        pattern: The relationship chain the expression tests.
    """

    pattern: RelationshipPattern

    def __post_init__(self) -> None:
        """
        Reject an input that is not a relationship chain.

        Raises:
            DslError: If the input is a node pattern, which is a label predicate in
                parentheses rather than a path pattern, or any value that is not a
                relationship chain.
        """
        if isinstance(self.pattern, NodePattern):
            raise DslError(
                "A node pattern alone is not a path pattern expression. "
                "Test labels with has_label() or connect the node through relationship_to()."
            )
        if not isinstance(self.pattern, RelationshipPattern):
            raise DslError(f"A path pattern expression takes a relationship chain, not {type(self.pattern).__name__}.")

    def children(self) -> tuple[AstNode, ...]:
        """Expose the chain as the only child."""
        return (self.pattern,)

    def local_names(self) -> tuple[str, ...]:
        """Return no names: every name inside the chain is a reference, not a binding."""
        return ()


def path_pattern(pattern: RelationshipPattern) -> PathPatternExpression:
    """
    Build a relationship chain as a boolean predicate.

    A path pattern expression is true when the chain matches at least once. It is the
    concise counterpart of ``exists()``: the chain references names an earlier clause
    binds and declares none of its own, and the expression is valid only where Cypher
    expects a boolean, so a projection negates or combines it instead of returning it
    bare.

    Args:
        pattern: The relationship chain the expression tests.

    Returns:
        A predicate usable wherever a condition is.

    Raises:
        DslError: If the input is a node pattern, which is a label predicate in
            parentheses rather than a path pattern, or any value that is not a
            relationship chain.
    """
    return PathPatternExpression(pattern)


__all__ = ["PathPatternExpression", "path_pattern"]

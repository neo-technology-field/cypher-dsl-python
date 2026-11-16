"""
The AST walk that renders one statement.

Each node is composed after its children, so a renderer receives their fragments in
`children()` order. The same walk assigns every node its `OccurrencePath`, which is how
one shared node appearing twice gets separate facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cypher_dsl.errors import UnsupportedFeatureError
from cypher_dsl.render.context import RenderContext
from cypher_dsl.render.fragments import Fragment
from cypher_dsl.render.rules import RenderingRules
from cypher_dsl.statements.analysis import Analysis
from cypher_dsl.syntax import AstNode, OccurrencePath, _Visitor


@dataclass(weakref_slot=True, slots=True)
class _Frame:
    """One node being visited, its occurrence path and the fragments its children produced."""

    node: AstNode
    path: OccurrencePath
    next_child_index: int = 0
    fragments: list[Fragment] = field(default_factory=list)


class RenderingTraversal(_Visitor):
    """Walk one AST and call the rule selected for a node once its children have produced fragments."""

    __slots__ = ("__weakref__", "_always_escape_names", "_analysis", "_frames", "_result", "_rules")

    def __init__(self, rules: RenderingRules, analysis: Analysis, always_escape_names: bool) -> None:
        """Store the immutable inputs for one render."""
        self._rules = rules
        self._analysis = analysis
        self._always_escape_names = always_escape_names
        self._frames: list[_Frame] = []
        self._result: str | None = None

    def enter(self, node: AstNode) -> None:
        """Push a frame for a node and assign its occurrence path from the parent's child order."""
        if self._frames:
            parent = self._frames[-1]
            path = (*parent.path, parent.next_child_index)
            parent.next_child_index += 1
        else:
            path = ()
        self._frames.append(_Frame(node, path))

    def leave(self, node: AstNode) -> None:
        """Compose one node through its selected rule and hand the resulting fragment to its parent."""
        if not self._frames or self._frames[-1].node is not node:
            raise UnsupportedFeatureError(f"Rendering traversal left {type(node).__name__} out of order.")
        frame = self._frames.pop()
        context = RenderContext(self._always_escape_names, self._analysis.facts_for(frame.path))
        text = self._rules.resolve(frame.node).compose(frame.node, tuple(frame.fragments), context)
        if self._frames:
            self._frames[-1].fragments.append(Fragment(frame.node, text))
        else:
            self._result = text

    def render(self, root: AstNode) -> str:
        """Render one root node and return its completed fragment."""
        root.accept(self)
        if self._result is None:
            raise UnsupportedFeatureError("No syntax tree was rendered.")
        return self._result


__all__ = ["RenderingTraversal"]

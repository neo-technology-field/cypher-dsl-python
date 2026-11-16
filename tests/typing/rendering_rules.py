"""
Static type-check fixture asserting that `bind` ties a renderer's first parameter to the node type it is
bound to. `pytest` does not collect this module and nothing imports it at run time.

`bind` takes `type[TNode]` and a callable whose first parameter is that same `TNode`, so the first argument
fixes the second. `literal_text` accepts `Literal` and is accepted. `variable_text` accepts `Variable` and is
rejected with `[arg-type]`, because `Literal` and `Variable` are sibling `Expression` subclasses and neither
stands in for the other.

`warn_unused_ignores = true` turns the `type: ignore[arg-type]` comment into part of the check. Removing the
`TNode` relation, or making `Literal` a `Variable`, would make the second binding legal, the ignore would
become unused, and `make typing` would fail.
"""

from cypher_dsl.expressions.values import Literal, Variable
from cypher_dsl.render.context import RenderContext
from cypher_dsl.render.fragments import Fragment
from cypher_dsl.render.rules import bind


def literal_text(node: Literal, children: tuple[Fragment, ...], context: RenderContext) -> str:
    return "literal"


def variable_text(node: Variable, children: tuple[Fragment, ...], context: RenderContext) -> str:
    return "variable"


valid = bind(Literal, literal_text)
# Rejected: `TNode` follows the node type, so the renderer must accept that same type.
invalid = bind(Literal, variable_text)  # type: ignore[arg-type]

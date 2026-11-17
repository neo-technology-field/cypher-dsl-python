"""
Static type-check fixture asserting that `_Visitor` and `NamedExpression` are nominal contracts. A class joins
them by inheriting, not by matching their members. `pytest` does not collect this module and nothing imports it at
run time.

`mypy` checks the file in strict mode and every annotation below is a claim it has to hold. Each contract is
stated twice: one class inherits and is accepted, one offers the same members without inheriting and must be
rejected. `_Visitor` covers the internal contract, `NamedExpression` the public one, and the pattern nodes show
that the node builders join it through inheritance.

`warn_unused_ignores = true` turns the two `type: ignore[assignment]` comments into part of the check. Turning
either contract into a `typing.Protocol` would make the undeclared assignments legal, both ignores would become
unused, and `make typing` would fail.
"""

from cypher_dsl import AstNode, Expression, NamedExpression, name, node
from cypher_dsl.ast import _Visitor


class UndeclaredVisitor:
    """Match the visitor callbacks without inheriting from `_Visitor`."""

    def enter(self, node: AstNode) -> None:
        """Ignore a node entry."""

    def leave(self, node: AstNode) -> None:
        """Ignore a node exit."""


class DeclaredVisitor(_Visitor):
    """Inherit the no-op callbacks from `_Visitor`."""


declared_visitor: _Visitor = DeclaredVisitor()
# Rejected: the seam is nominal, matching callbacks alone do not qualify.
undeclared_visitor: _Visitor = UndeclaredVisitor()  # type: ignore[assignment]


class UndeclaredNamedExpression:
    """Match the conversion signature without inheriting from `NamedExpression`."""

    def as_expression(self) -> Expression:
        """Return a variable expression."""
        return name("p")


named_node: NamedExpression = node("Person", name="p")
named_relationship: NamedExpression = node("Person", name="p").relationship_to(
    node("Movie", name="m"), "ACTED_IN", name="r"
)
# Rejected: the seam is nominal, the signature alone does not qualify.
undeclared_expression: NamedExpression = UndeclaredNamedExpression()  # type: ignore[assignment]

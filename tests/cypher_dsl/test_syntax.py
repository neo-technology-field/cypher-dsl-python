"""
Traversal and structural comparison contracts for shared syntax nodes.

The composite used here stands in for a statement-shaped child so that nested enter and
leave ordering is pinned without adding a public clause.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from cypher_dsl import AstNode, lit, name, structurally_equal
from cypher_dsl.syntax import _Visitor


def test_literals_snapshot_nested_input():
    original = {"values": [1, 2]}
    first = lit(original)
    original["values"].append(3)
    assert structurally_equal(first, lit({"values": [1, 2]}))
    assert not structurally_equal(first, lit(original))


def test_literal_accepts_a_driver_free_visitor():
    events = []

    class RecordingVisitor(_Visitor):
        def enter(self, node):
            events.append(("enter", type(node).__name__))

        def leave(self, node):
            events.append(("leave", type(node).__name__))

    lit(1).accept(RecordingVisitor())
    assert events == [("enter", "Literal"), ("leave", "Literal")]


@dataclass(frozen=True, eq=False)
class _TestLeaf(AstNode):
    label: str


@dataclass(frozen=True, eq=False)
class _TestComposite(AstNode):
    parts: tuple[AstNode, ...]

    def children(self) -> tuple[AstNode, ...]:
        return self.parts


def test_traversal_visits_nested_children_in_documented_order():
    events = []

    class RecordingVisitor(_Visitor):
        def enter(self, node):
            events.append(("enter", getattr(node, "label", "composite")))

        def leave(self, node):
            events.append(("leave", getattr(node, "label", "composite")))

    tree = _TestComposite((_TestLeaf("first"), _TestLeaf("second")))
    tree.accept(RecordingVisitor())
    assert events == [
        ("enter", "composite"),
        ("enter", "first"),
        ("leave", "first"),
        ("enter", "second"),
        ("leave", "second"),
        ("leave", "composite"),
    ]


def test_leaf_nodes_report_no_children():
    assert lit(1).children() == ()


def test_declared_visitor_is_a_nominal_subclass():
    class DeclaredVisitor(_Visitor):
        pass

    assert isinstance(DeclaredVisitor(), _Visitor)
    assert _Visitor in DeclaredVisitor.__mro__


def test_visitor_callbacks_do_nothing():
    visitor = _Visitor()
    visitor.enter(lit(1))
    visitor.leave(lit(1))


def test_visitors_are_not_exported_from_the_public_facade():
    import cypher_dsl

    for symbol in ("Visitor", "BaseVisitor"):
        assert symbol not in cypher_dsl.__all__
        assert not hasattr(cypher_dsl, symbol)


def test_visitor_membership_requires_declared_inheritance():
    class UndeclaredVisitor:
        def enter(self, node: AstNode) -> None:
            pass

        def leave(self, node: AstNode) -> None:
            pass

    assert not isinstance(UndeclaredVisitor(), _Visitor)


@dataclass(frozen=True, eq=False)
class _ExplodingNode(AstNode):
    value: int

    def __eq__(self, other):
        raise AssertionError("structural comparison must not call expression ==")


def test_structural_comparison_never_calls_expression_equality():
    assert structurally_equal(_ExplodingNode(1), _ExplodingNode(1))
    assert not structurally_equal(_ExplodingNode(1), _ExplodingNode(2))


def test_structural_comparison_uses_node_types():
    assert not structurally_equal(lit(1), name("1"))


def test_structural_comparison_compares_symbolic_names_by_value():
    assert structurally_equal(name("movie"), name("movie"))
    assert not structurally_equal(name("movie"), name("actor"))


def test_structural_comparison_distinguishes_booleans_from_integers():
    assert structurally_equal(lit(True), lit(True))
    assert not structurally_equal(lit(True), lit(1))


def test_expressions_reject_boolean_evaluation():
    with pytest.raises(TypeError, match="boolean"):
        bool(lit(1))


def test_expressions_are_not_hashable():
    with pytest.raises(TypeError):
        hash(lit(1))

"""Tests for the generic post-order fragment traversal."""

from dataclasses import dataclass

import pytest

from cypher_dsl.ast import AstNode, OccurrenceFacts, OccurrencePath
from cypher_dsl.errors import UnsupportedFeatureError
from cypher_dsl.expressions.base import Expression
from cypher_dsl.render.context import RenderContext
from cypher_dsl.render.fragments import Fragment
from cypher_dsl.render.rules import RenderingRules, bind
from cypher_dsl.render.traversal import RenderingTraversal
from cypher_dsl.statements.analysis import Analysis, NoFacts


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class Word(Expression):
    value: str


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class Pair(AstNode):
    left: Word
    right: Word

    def children(self) -> tuple[AstNode, ...]:
        return (self.left, self.right)


def word(node: Word, children: tuple[Fragment, ...], context: RenderContext) -> str:
    return node.value.upper()


@dataclass(frozen=True, weakref_slot=True, slots=True)
class LabelFacts(OccurrenceFacts):
    label: str


def labelled_word(node: Word, children: tuple[Fragment, ...], context: RenderContext) -> str:
    facts = context.facts
    return facts.label if isinstance(facts, LabelFacts) else "?"


def pair(node: Pair, children: tuple[Fragment, ...], context: RenderContext) -> str:
    return f"{children[0].text}|{children[1].text}"


def analysis_with_paths(root: AstNode) -> Analysis:
    facts: dict[OccurrencePath, NoFacts] = {}

    def walk(node: AstNode, path: OccurrencePath) -> None:
        facts[path] = NoFacts()
        for index, child in enumerate(node.children()):
            walk(child, (*path, index))

    walk(root, ())
    return Analysis(facts, (), ())


def test_synthetic_tree_renders_without_production_cypher_types() -> None:
    root = Pair(Word("a"), Word("b"))
    rules = RenderingRules.from_bindings((bind(Word, word), bind(Pair, pair)))
    assert RenderingTraversal(rules, analysis_with_paths(root), always_escape_names=False).render(root) == "A|B"


def test_child_order_is_stable_for_shared_node_objects() -> None:
    shared = Word("x")
    root = Pair(shared, shared)
    rules = RenderingRules.from_bindings((bind(Word, word), bind(Pair, pair)))
    assert RenderingTraversal(rules, analysis_with_paths(root), False).render(root) == "X|X"


def test_occurrence_paths_distinguish_repeated_node_objects() -> None:
    shared = Word("x")
    root = Pair(shared, shared)
    facts: dict[OccurrencePath, OccurrenceFacts] = {
        (): LabelFacts("root"),
        (0,): LabelFacts("left"),
        (1,): LabelFacts("right"),
    }
    rules = RenderingRules.from_bindings((bind(Word, labelled_word), bind(Pair, pair)))
    assert RenderingTraversal(rules, Analysis(facts, (), ()), False).render(root) == "left|right"


def test_unknown_node_names_its_type() -> None:
    @dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
    class Unknown(Expression):
        pass

    with pytest.raises(UnsupportedFeatureError, match="Unknown"):
        RenderingTraversal(RenderingRules.from_bindings(()), analysis_with_paths(Unknown()), False).render(Unknown())


def test_out_of_order_leave_is_rejected() -> None:
    root = Pair(Word("a"), Word("b"))
    rules = RenderingRules.from_bindings((bind(Word, word), bind(Pair, pair)))
    traversal = RenderingTraversal(rules, analysis_with_paths(root), False)
    traversal.enter(root)
    with pytest.raises(UnsupportedFeatureError, match="out of order"):
        traversal.leave(root.left)

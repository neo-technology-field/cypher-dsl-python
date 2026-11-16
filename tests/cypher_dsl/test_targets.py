"""Resolved releases, language prefixes and immutable rendering rules."""

from dataclasses import dataclass, replace

import pytest

from cypher_dsl import Configuration, Language
from cypher_dsl.errors import UnsupportedFeatureError
from cypher_dsl.features import Capability
from cypher_dsl.render.context import RenderContext
from cypher_dsl.render.fragments import Fragment
from cypher_dsl.render.rules import RenderingRules, bind
from cypher_dsl.render.targets import ResolvedTarget, resolve_target
from cypher_dsl.render.traversal import RenderingTraversal
from cypher_dsl.statements.analysis import Analysis, SyntaxRequirement
from cypher_dsl.syntax import AstNode


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class SyntheticTargetNode(AstNode):
    text: str


def shared_synthetic(node: SyntheticTargetNode, children: tuple[Fragment, ...], context: RenderContext) -> str:
    return f"shared:{node.text}"


def replacement_synthetic(node: SyntheticTargetNode, children: tuple[Fragment, ...], context: RenderContext) -> str:
    return f"replacement:{node.text}"


def render(root: AstNode, rules: RenderingRules) -> str:
    return RenderingTraversal(rules, Analysis({}, (), ()), always_escape_names=False).render(root)


def test_resolved_targets_are_immutable_and_share_rules() -> None:
    first = resolve_target(Configuration(server_version="5.26"))
    second = resolve_target(Configuration(server_version="2026.10", language=Language.CYPHER_25))
    assert isinstance(first, ResolvedTarget)
    assert first.rules is second.rules
    with pytest.raises(AttributeError):
        first.language = Language.CYPHER_5


@pytest.mark.parametrize(
    ("language", "plain_prefix", "search_prefix"),
    [
        (Language.AUTO, "", "CYPHER 25 "),
        (Language.NONE, "", ""),
        (Language.CYPHER_5, "CYPHER 5 ", "CYPHER 5 "),
        (Language.CYPHER_25, "CYPHER 25 ", "CYPHER 25 "),
    ],
)
def test_language_prefix_is_selected_per_requirement_set(language, plain_prefix, search_prefix) -> None:
    target = resolve_target(Configuration(server_version="2026.10", language=language))
    search = (SyntaxRequirement(Capability.VECTOR_SEARCH, (0,)),)
    assert target.language_prefix(()) == plain_prefix
    assert target.language_prefix(search) == search_prefix
    assert target.language_prefix(()) == plain_prefix


def test_automatic_language_checks_all_requirements_and_selects_the_needed_prefix() -> None:
    target = resolve_target(Configuration(server_version="2026.10", always_escape_names=True))
    requirements = (
        SyntaxRequirement(Capability.DYNAMIC_PROPERTY_WRITES, (0,)),
        SyntaxRequirement(Capability.VECTOR_SEARCH, (1,)),
        SyntaxRequirement(Capability.FULLTEXT_SEARCH, (2,)),
    )
    target.check_requirements(requirements)
    assert target.effective_language(requirements) is Language.CYPHER_25
    assert target.language_prefix(requirements) == "CYPHER 25 "
    assert target.always_escape_names is True


def test_a_later_requirement_still_checks_its_release_floor() -> None:
    target = resolve_target(Configuration(server_version="2026.08"))
    requirements = (
        SyntaxRequirement(Capability.VECTOR_SEARCH, (0,)),
        SyntaxRequirement(Capability.FULLTEXT_SEARCH, (1,)),
    )
    with pytest.raises(UnsupportedFeatureError, match=r"FULLTEXT_SEARCH requires Neo4j 2026\.09 or later"):
        target.check_requirements(requirements)


def test_replacement_rule_changes_target_output_without_changing_traversal() -> None:
    node = SyntheticTargetNode("value")
    target = resolve_target(Configuration(server_version="5.26"))
    shared_rules = RenderingRules.from_bindings((bind(SyntheticTargetNode, shared_synthetic),))
    replacement_rules = RenderingRules.from_bindings((bind(SyntheticTargetNode, replacement_synthetic),))
    shared_target = replace(target, rules=shared_rules)
    replacement_target = replace(target, rules=replacement_rules)
    assert render(node, replacement_target.rules) == "replacement:value"
    assert render(node, shared_target.rules) == "shared:value"

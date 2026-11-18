"""Label expression predicates: rendering, validation and target floors."""

import pytest

from cypher_dsl import (
    Configuration,
    Language,
    Renderer,
    count,
    fn,
    has_label,
    is_labeled,
    is_not_labeled,
    label,
    match,
    node,
)
from cypher_dsl.errors import DslError, UnsupportedFeatureError
from cypher_dsl.expressions.base import Precedence
from cypher_dsl.expressions.labels import HasLabel, IsLabeled
from cypher_dsl.patterns.labels import ANY_LABEL, ColonConjunction, LabelConjunction

RENDERER = Renderer.get(Configuration(server_version="5.26"))
PERSON = node("Person", name="p")


def test_has_label_renders_one_label() -> None:
    statement = match(PERSON).where(has_label(PERSON, "Manager")).returning(PERSON["uid"])

    assert RENDERER.render(statement).cypher == "MATCH (p:Person) WHERE p:Manager RETURN p.uid"


def test_has_label_renders_label_expression_terms() -> None:
    statement = match(PERSON).where(has_label(PERSON, label("Manager") | label("Director"))).returning(PERSON)

    assert RENDERER.render(statement).cypher == "MATCH (p:Person) WHERE p:Manager|Director RETURN p"


def test_has_label_renders_negation_and_wildcard() -> None:
    negated = match(PERSON).where(has_label(PERSON, ~label("CEO"))).returning(PERSON)
    wildcard = match(PERSON).where(has_label(PERSON, ANY_LABEL)).returning(PERSON)

    assert RENDERER.render(negated).cypher == "MATCH (p:Person) WHERE p:!CEO RETURN p"
    assert RENDERER.render(wildcard).cypher == "MATCH (p:Person) WHERE p:% RETURN p"


def test_has_label_tests_a_relationship_type() -> None:
    report = node("Person", name="c").relationship_to(PERSON, name="r")
    statement = match(report).where(has_label(report, "WORKS_FOR")).returning(PERSON["uid"])

    assert RENDERER.render(statement).cypher == "MATCH (c:Person)-[r]->(p:Person) WHERE r:WORKS_FOR RETURN p.uid"


def test_has_label_accepts_any_expression_as_the_element() -> None:
    movie = node("Movie", name="m")
    element = fn("coalesce", PERSON, movie)
    statement = match(PERSON, movie).where(has_label(element, "Manager")).returning(PERSON)

    assert RENDERER.render(statement).cypher == "MATCH (p:Person), (m:Movie) WHERE coalesce(p, m):Manager RETURN p"


def test_has_label_combines_with_other_conditions_without_added_parentheses() -> None:
    statement = (
        match(PERSON)
        .where((has_label(PERSON, label("Manager") | label("Director"))) & (PERSON["age"] > 30))
        .returning(PERSON)
    )

    assert RENDERER.render(statement).cypher == "MATCH (p:Person) WHERE p:Manager|Director AND p.age > 30 RETURN p"


def test_negated_has_label_renders_without_parentheses() -> None:
    statement = match(PERSON).where(~has_label(PERSON, "Manager")).returning(PERSON)

    assert RENDERER.render(statement).cypher == "MATCH (p:Person) WHERE NOT p:Manager RETURN p"


def test_has_label_projects_under_an_alias() -> None:
    statement = match(PERSON).returning(has_label(PERSON, "Manager").alias("isManager"))

    assert RENDERER.render(statement).cypher == "MATCH (p:Person) RETURN p:Manager AS isManager"


def test_has_label_builds_a_comparison_level_condition() -> None:
    predicate = has_label(PERSON, "Manager")

    assert isinstance(predicate, HasLabel)
    assert predicate.precedence is Precedence.COMPARISON


def test_has_label_rejects_a_colon_conjunction() -> None:
    with pytest.raises(DslError, match="colon list"):
        has_label(PERSON, ColonConjunction((label("A"), label("B"))))


def test_has_label_rejects_a_nested_colon_conjunction() -> None:
    nested = LabelConjunction(label("A"), ColonConjunction((label("B"), label("C"))))

    with pytest.raises(DslError, match="colon list"):
        has_label(PERSON, nested)


def test_has_label_rejects_a_bare_string_element() -> None:
    with pytest.raises(DslError, match="not str"):
        has_label("Person", "Manager")  # type: ignore[arg-type]


def test_has_label_rejects_a_non_term_labels_value() -> None:
    with pytest.raises(DslError, match="not int"):
        has_label(PERSON, 3)  # type: ignore[arg-type]


def test_direct_construction_rejects_a_non_term_labels_value() -> None:
    with pytest.raises(DslError, match="holds a label expression, not int"):
        HasLabel(PERSON.as_expression(), 3)  # type: ignore[arg-type]


def test_is_labeled_direct_construction_rejects_a_non_term_labels_value() -> None:
    with pytest.raises(DslError, match="holds a label expression, not int"):
        IsLabeled(PERSON.as_expression(), 3)  # type: ignore[arg-type]


def test_has_label_rejects_an_anonymous_pattern() -> None:
    with pytest.raises(DslError):
        has_label(node("Person"), "Manager")


def test_has_label_rejects_an_alias_operand() -> None:
    with pytest.raises(DslError, match="alias"):
        has_label(PERSON["uid"].alias("uid"), "Manager")


def test_has_label_reads_the_scope_of_its_operand() -> None:
    statement = match(PERSON).with_(count(PERSON).alias("people"))

    with pytest.raises(DslError, match="'p', which is not in scope"):
        statement.where(has_label(PERSON, "Manager"))


def test_is_labeled_renders_with_the_cypher_25_prefix_under_auto() -> None:
    statement = match(PERSON).where(is_labeled(PERSON, "Manager")).returning(PERSON["uid"])
    renderer = Renderer.get(Configuration(server_version="2026.10"))

    assert renderer.render(statement).cypher == "CYPHER 25 MATCH (p:Person) WHERE p IS LABELED Manager RETURN p.uid"


def test_is_labeled_renders_label_expression_terms() -> None:
    statement = match(PERSON).where(is_labeled(PERSON, label("Manager") | label("Director"))).returning(PERSON)
    renderer = Renderer.get(Configuration(server_version="2026.10"))

    assert (
        renderer.render(statement).cypher == "CYPHER 25 MATCH (p:Person) WHERE p IS LABELED Manager|Director RETURN p"
    )


def test_is_not_labeled_negates_the_whole_expression() -> None:
    statement = match(PERSON).where(is_not_labeled(PERSON, label("A") & label("B"))).returning(PERSON)
    renderer = Renderer.get(Configuration(server_version="2026.10"))

    assert renderer.render(statement).cypher == "CYPHER 25 MATCH (p:Person) WHERE p IS NOT LABELED A&B RETURN p"


def test_negation_semantics_stay_distinct() -> None:
    inside = match(PERSON).where(has_label(PERSON, ~label("A") & label("B"))).returning(PERSON)
    outside = match(PERSON).where(is_not_labeled(PERSON, label("A") & label("B"))).returning(PERSON)
    # A CYPHER 25 pin gives both statements the same prefix, so the predicate is the only difference.
    renderer = Renderer.get(Configuration(server_version="2026.10", language=Language.CYPHER_25))

    assert renderer.render(inside).cypher == "CYPHER 25 MATCH (p:Person) WHERE p:!A&B RETURN p"
    assert renderer.render(outside).cypher == "CYPHER 25 MATCH (p:Person) WHERE p IS NOT LABELED A&B RETURN p"


def test_is_labeled_below_the_2026_04_floor_is_refused() -> None:
    statement = match(PERSON).where(is_labeled(PERSON, "Manager")).returning(PERSON)
    renderer = Renderer.get(Configuration(server_version="2026.03"))

    with pytest.raises(UnsupportedFeatureError, match=r"IS_LABELED requires Neo4j 2026\.04 or later"):
        renderer.render(statement)


def test_is_labeled_under_a_cypher_5_pin_is_refused() -> None:
    statement = match(PERSON).where(is_labeled(PERSON, "Manager")).returning(PERSON)
    renderer = Renderer.get(Configuration(server_version="2026.10", language=Language.CYPHER_5))

    with pytest.raises(UnsupportedFeatureError, match="requires Cypher 25, but language is set to CYPHER 5"):
        renderer.render(statement)


def test_is_labeled_with_a_suppressed_prefix_still_checks_the_release() -> None:
    statement = match(PERSON).where(is_labeled(PERSON, "Manager")).returning(PERSON)
    renderer = Renderer.get(Configuration(server_version="2026.03", language=Language.NONE))

    with pytest.raises(UnsupportedFeatureError, match=r"IS_LABELED requires Neo4j 2026\.04 or later"):
        renderer.render(statement)

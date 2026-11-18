"""
Node patterns, relationship directions, chains and pattern references.

Patterns are syntax, not rendered text. These tests pin the separation between a
pattern's identity (its variable), its labels and its property map, and they pin that a
pattern used as an expression becomes the bare variable.
"""

from __future__ import annotations

import pytest

from cypher_dsl import (
    Configuration,
    Expression,
    NamedExpression,
    NodePattern,
    PatternElement,
    PatternProperties,
    Relationship,
    RelationshipDirection,
    RelationshipPattern,
    Renderer,
    SymbolicName,
    Variable,
    count,
    lit,
    match,
    name,
    node,
    param,
    returning,
    structurally_equal,
)
from cypher_dsl.errors import DslError, EmptyPatternError, InvalidIdentifierError, InvalidLiteralError
from cypher_dsl.expressions.base import coerce_expression
from cypher_dsl.patterns.labels import ColonConjunction, LabelName, label

_RETURN_REF = " RETURN ref"


def _pattern(element):
    """Render one pattern element inside a MATCH and return just the pattern text."""
    rendered = Renderer.get(Configuration(server_version="5.26")).render(match(element).returning(name("ref")))
    assert rendered.cypher.startswith("MATCH ")
    assert rendered.cypher.endswith(_RETURN_REF)
    return rendered.cypher.removeprefix("MATCH ").removesuffix(_RETURN_REF)


def test_node_pattern_keeps_label_variable_and_properties_separate():
    movie = node("Movie", name="m", properties={"title": "The Matrix", "released": 1999})
    assert isinstance(movie, NodePattern)
    assert _pattern(movie) == "(m:Movie {title: 'The Matrix', released: 1999})"


def test_a_variable_is_not_a_name_property():
    person = node("Person", name="p", properties={"name": "Ada"})
    assert person.variable == SymbolicName("p")
    assert _pattern(person) == "(p:Person {`name`: 'Ada'})"
    assert _pattern(node("Person", properties={"name": "Ada"})) == "(:Person {`name`: 'Ada'})"


def test_with_labels_returns_a_new_node_with_unique_labels_in_insertion_order():
    base = node("Person", name="p")
    extended = base.with_labels("Actor", "Director", "Actor")
    assert extended is not base
    assert isinstance(base.label_expression, LabelName)
    assert base.label_expression.name.value == "Person"
    assert isinstance(extended.label_expression, ColonConjunction)
    assert [term.name.value for term in extended.label_expression.terms] == ["Person", "Actor", "Director"]
    assert _pattern(extended) == "(p:Person:Actor:Director)"


def test_relationship_directions_are_explicit_values():
    person = node("Person", name="p")
    colleague = node("Person", name="c")
    assert person.relationship_to(colleague, "KNOWS").direction is RelationshipDirection.OUTGOING
    assert person.relationship_from(colleague, "KNOWS").direction is RelationshipDirection.INCOMING
    assert person.relationship_with(colleague, "KNOWS").direction is RelationshipDirection.UNDIRECTED


def test_all_directions_render_from_the_left_node():
    person = node("Person", name="p")
    colleague = node("Person", name="c")
    assert _pattern(person.relationship_to(colleague, "KNOWS")) == "(p:Person)-[:KNOWS]->(c:Person)"
    assert _pattern(person.relationship_from(colleague, "KNOWS")) == "(p:Person)<-[:KNOWS]-(c:Person)"
    assert _pattern(person.relationship_with(colleague, "KNOWS")) == "(p:Person)-[:KNOWS]-(c:Person)"


def test_relationship_name_and_properties_render_inside_the_brackets():
    person = node("Person", name="p")
    colleague = node("Person", name="c")
    knows = person.relationship_to(colleague, "KNOWS", name="r", properties={"since": 1999})
    assert _pattern(knows) == "(p:Person)-[r:KNOWS {since: 1999}]->(c:Person)"


def test_anonymous_relationships_without_details_have_no_brackets():
    relationship = Relationship(
        node("Person", name="p"),
        node("Movie", name="m"),
        RelationshipDirection.OUTGOING,
    )
    assert _pattern(RelationshipPattern((relationship,))) == "(p:Person)-->(m:Movie)"


def test_anonymous_endpoints_render_but_cannot_become_references():
    person = node("Person", name="p")
    acted = person.relationship_to(node("Movie"), "ACTED_IN", name="r")
    assert _pattern(acted) == "(p:Person)-[r:ACTED_IN]->(:Movie)"


def test_named_patterns_render_as_variable_references():
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    acted = person.relationship_to(movie, "ACTED_IN", name="r")
    renderer = Renderer.get(Configuration(server_version="5.26"))
    assert renderer.render(returning(person)).cypher == "RETURN p"
    assert renderer.render(returning(acted)).cypher == "RETURN r"
    assert renderer.render(returning(acted["weight"])).cypher == "RETURN r.weight"
    assert renderer.render(returning(count(acted))).cypher == "RETURN count(r)"
    reference: Variable = person.as_expression()
    assert reference.symbol == SymbolicName("p")
    assert structurally_equal(acted.as_expression(), Variable(SymbolicName("r")))


class _UndeclaredNamedExpression:
    """Provide a conversion method without declaring the contract."""

    def as_expression(self) -> Expression:
        """Fail if an undeclared conversion is invoked."""
        raise AssertionError("An undeclared conversion must not be called.")


def test_pattern_classes_declare_named_expression_membership():
    person = node("Person", name="p")
    relationship = person.relationship_to(node("Movie", name="m"), "ACTED_IN", name="r")
    assert NamedExpression in NodePattern.__mro__
    assert NamedExpression in RelationshipPattern.__mro__
    assert isinstance(person, NamedExpression)
    assert isinstance(relationship, NamedExpression)
    assert not isinstance(PatternElement(), NamedExpression)


def test_named_expression_requires_an_implementation():
    class IncompleteExpression(NamedExpression):
        pass

    with pytest.raises(TypeError, match="as_expression"):
        IncompleteExpression()


def test_named_expression_membership_rejects_an_undeclared_conversion():
    assert not isinstance(_UndeclaredNamedExpression(), NamedExpression)


@pytest.mark.parametrize("convert", (coerce_expression, returning))
def test_expression_inputs_reject_an_undeclared_conversion(convert):
    with pytest.raises(InvalidLiteralError):
        convert(_UndeclaredNamedExpression())


def test_anonymous_patterns_explain_that_a_name_is_required():
    anonymous_node = node("Movie")
    with pytest.raises(DslError, match="name"):
        anonymous_node.as_expression()
    with pytest.raises(DslError, match="name"):
        anonymous_node["title"]
    with pytest.raises(DslError, match="name"):
        returning(anonymous_node)
    anonymous_relationship = node("Person", name="p").relationship_to(node("Movie"), "ACTED_IN")
    with pytest.raises(DslError, match="name"):
        anonymous_relationship.as_expression()
    with pytest.raises(DslError, match="name"):
        count(anonymous_relationship)


def test_chains_extend_from_the_current_endpoint():
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    studio = node("Studio", name="s")
    chain = person.relationship_to(movie, "ACTED_IN", name="r").relationship_with(studio, "PRODUCED_BY")
    assert chain.start is person
    assert chain.endpoint is studio
    assert [relationship.right for relationship in chain.relationships] == [movie, studio]
    assert _pattern(chain) == "(p:Person)-[r:ACTED_IN]->(m:Movie)-[:PRODUCED_BY]-(s:Studio)"


def test_reused_named_endpoints_stay_the_same_reference():
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    pattern = person.relationship_to(movie, "ACTED_IN").relationship_to(person, "DIRECTED")
    assert _pattern(pattern) == "(p:Person)-[:ACTED_IN]->(m:Movie)-[:DIRECTED]->(p:Person)"


def test_direct_chain_construction_rejects_disagreeing_adjacent_endpoints():
    first = node("Person", name="p").relationship_to(node("Movie", name="m"), "ACTED_IN")
    disagreeing = node("Movie", name="m").relationship_to(node("Studio", name="s"), "PRODUCED_BY")
    assert first.endpoint is not disagreeing.relationships[0].left
    with pytest.raises(DslError, match="endpoint"):
        RelationshipPattern((first.relationships[0], disagreeing.relationships[0]))
    accepted = RelationshipPattern(first.relationships)
    assert _pattern(accepted) == "(p:Person)-[:ACTED_IN]->(m:Movie)"


def test_empty_chains_and_match_arguments_are_rejected():
    with pytest.raises(EmptyPatternError):
        RelationshipPattern(())
    with pytest.raises(DslError, match="pattern"):
        match("Movie")


def test_relationship_endpoint_must_be_a_node_pattern():
    person = node("Person", name="p")
    with pytest.raises(DslError, match="node"):
        person.relationship_to("Movie", "ACTED_IN")


def test_pattern_property_maps_snapshot_caller_input():
    properties = {"title": "The Matrix"}
    movie = node("Movie", name="m", properties=properties)
    relationship_properties = {"since": 1999}
    knows = node("Person", name="p").relationship_to(
        node("Person", name="c"), "KNOWS", properties=relationship_properties
    )
    properties["title"] = "Changed"
    relationship_properties["since"] = 2024
    assert _pattern(movie) == "(m:Movie {title: 'The Matrix'})"
    assert _pattern(knows) == "(p:Person)-[:KNOWS {since: 1999}]->(c:Person)"


def test_pattern_property_values_are_expressions_not_string_interpolation():
    movie = node("Movie", name="m", properties={"title": param("title"), "tagline": "The question is."})
    assert _pattern(movie) == "(m:Movie {title: $title, tagline: 'The question is.'})"


def test_direct_property_map_construction_rejects_an_aliased_value():
    with pytest.raises(DslError, match="alias"):
        PatternProperties(((SymbolicName("title"), lit("x").alias("other")),))
    accepted = PatternProperties(((SymbolicName("title"), lit("x")),))
    movie = NodePattern(LabelName(SymbolicName("Movie")), SymbolicName("m"), accepted)
    assert _pattern(movie) == "(m:Movie {title: 'x'})"


def test_direct_node_construction_rejects_an_aliased_property_value():
    with pytest.raises(DslError, match="alias"):
        NodePattern(
            LabelName(SymbolicName("Movie")),
            SymbolicName("m"),
            PatternProperties(((SymbolicName("title"), lit("x").alias("other")),)),
        )


def test_direct_relationship_construction_rejects_an_aliased_property_value():
    with pytest.raises(DslError, match="alias"):
        Relationship(
            node("Person", name="p"),
            node("Movie", name="m"),
            RelationshipDirection.OUTGOING,
            label("ACTED_IN"),
            properties=PatternProperties(((SymbolicName("role"), lit("x").alias("other")),)),
        )


@pytest.mark.parametrize("bad_label", ["", "bad\nlabel", "x\x00y", r"x\u0060y"])
def test_invalid_labels_fail_at_the_pattern_boundary(bad_label):
    with pytest.raises(InvalidIdentifierError):
        node(bad_label)


@pytest.mark.parametrize("bad_name", ["", "bad\nvariable", "x\x00y", r"x\u0060y"])
def test_invalid_variables_fail_at_the_pattern_boundary(bad_name):
    with pytest.raises(InvalidIdentifierError):
        node("Person", name=bad_name)


@pytest.mark.parametrize("bad_name", ["bad\nlabel", r"x\u0060y"])
def test_invalid_additional_labels_fail_at_the_pattern_boundary(bad_name):
    with pytest.raises(InvalidIdentifierError):
        node("Person", name="p").with_labels(bad_name)


@pytest.mark.parametrize("bad_name", ["", "BAD\nTYPE", r"x\u0060y"])
def test_invalid_relationship_types_fail_at_the_pattern_boundary(bad_name):
    with pytest.raises(InvalidIdentifierError):
        node("Person", name="p").relationship_to(node("Movie", name="m"), bad_name)


def test_invalid_relationship_variables_and_property_keys_fail_at_the_pattern_boundary():
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    with pytest.raises(InvalidIdentifierError):
        person.relationship_to(movie, "ACTED_IN", name="bad\nvariable")
    with pytest.raises(InvalidIdentifierError):
        node("Movie", name="m", properties={"bad\nkey": 1})


def test_with_labels_requires_at_least_one_label():
    with pytest.raises(DslError, match="label"):
        node("Person", name="p").with_labels()


def test_pattern_elements_expose_the_nodes_they_contain():
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    studio = node("Studio", name="s")
    chain = person.relationship_to(movie, "ACTED_IN").relationship_with(studio, "PRODUCED_BY")
    assert isinstance(person, PatternElement)
    assert isinstance(chain, PatternElement)
    assert person.nodes() == (person,)
    assert chain.nodes() == (person, movie, studio)


def test_untyped_relationships_render_through_each_direction_factory():
    person = node("Person", name="a")
    other = node("Person", name="b")
    assert _pattern(person.relationship_to(other)) == "(a:Person)-->(b:Person)"
    assert _pattern(person.relationship_from(other)) == "(a:Person)<--(b:Person)"
    assert _pattern(person.relationship_with(other)) == "(a:Person)--(b:Person)"


def test_an_untyped_relationship_with_a_variable_renders_the_bracket():
    person = node("Person", name="a")
    other = node("Person", name="b")
    relationship = person.relationship_to(other, name="r")
    assert _pattern(relationship) == "(a:Person)-[r]->(b:Person)"
    assert _pattern(person.relationship_to(other, None, name="r")) == "(a:Person)-[r]->(b:Person)"


def test_an_untyped_relationship_with_properties_renders_only_the_map():
    person = node("Person", name="a")
    other = node("Person", name="b")
    relationship = person.relationship_with(other, properties={"since": 1})
    assert _pattern(relationship) == "(a:Person)-[{since: 1}]-(b:Person)"


def test_a_chain_mixes_typed_and_untyped_relationships():
    person = node("Person", name="a")
    movie = node("Movie", name="m")
    series = node("Series", name="s")
    path = person.relationship_to(movie, "ACTED_IN").relationship_with(series)
    assert _pattern(path) == "(a:Person)-[:ACTED_IN]->(m:Movie)--(s:Series)"


def test_a_named_untyped_relationship_is_usable_as_an_expression():
    person = node("Person", name="a")
    other = node("Person", name="b")
    relationship = person.relationship_to(other, name="r")
    rendered = Renderer.get(Configuration(server_version="5.26")).render(match(relationship).returning(relationship))
    assert rendered.cypher == "MATCH (a:Person)-[r]->(b:Person) RETURN r"


def test_an_empty_relationship_type_is_still_rejected():
    person = node("Person", name="a")
    other = node("Person", name="b")
    with pytest.raises(InvalidIdentifierError, match="empty"):
        person.relationship_to(other, "")

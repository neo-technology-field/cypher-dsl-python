"""Label expression terms: operator behaviour, validation and write-position rules."""

import pytest

from cypher_dsl import (
    Configuration,
    Relationship,
    RelationshipDirection,
    Renderer,
    SymbolicName,
    create,
    merge,
    node,
)
from cypher_dsl.errors import DslError, InvalidIdentifierError
from cypher_dsl.patterns.labels import (
    ANY_LABEL,
    AnyLabel,
    ColonConjunction,
    LabelConjunction,
    LabelDisjunction,
    LabelName,
    LabelNegation,
    LabelPrecedence,
    label,
)
from cypher_dsl.patterns.nodes import NodePattern


def test_operators_build_the_matching_terms():
    a, b, c = label("A"), label("B"), label("C")

    assert isinstance(a & b, LabelConjunction)
    assert isinstance(a | b, LabelDisjunction)
    assert isinstance(~a, LabelNegation)
    # Python precedence matches Cypher: & binds tighter than |.
    assert isinstance(a & b | c, LabelDisjunction)
    assert isinstance((a & b | c).left, LabelConjunction)
    assert isinstance(a | b & c, LabelDisjunction)
    assert isinstance((a | b & c).right, LabelConjunction)


def test_operators_reject_non_label_operands():
    with pytest.raises(TypeError):
        label("A") & "B"
    with pytest.raises(TypeError):
        label("A") | "B"


def test_label_name_validates_its_name():
    with pytest.raises(InvalidIdentifierError):
        label("")


def test_wildcard_is_a_singleton_atom():
    assert isinstance(ANY_LABEL, AnyLabel)
    assert ANY_LABEL.precedence == LabelPrecedence.ATOM


def test_colon_conjunction_requires_two_label_names():
    with pytest.raises(DslError):
        ColonConjunction((label("A"),))
    with pytest.raises(DslError):
        ColonConjunction((label("A"), ANY_LABEL))


def test_direct_construction_rejects_non_terms():
    with pytest.raises(DslError):
        LabelConjunction(label("A"), "B")  # type: ignore[arg-type]
    with pytest.raises(DslError):
        LabelDisjunction("A", label("B"))  # type: ignore[arg-type]
    with pytest.raises(DslError):
        LabelNegation("A")  # type: ignore[arg-type]


def test_term_precedence_order():
    # Manual: () > ! > & > |. Parenthesised grouping is tested through rendering in Task 4.
    assert LabelPrecedence.ATOM > LabelPrecedence.NEGATION
    assert LabelPrecedence.NEGATION > LabelPrecedence.CONJUNCTION
    assert LabelPrecedence.CONJUNCTION > LabelPrecedence.DISJUNCTION


def test_node_accepts_a_label_expression():
    pattern = node(label("Movie") | label("Person"), name="n")

    assert isinstance(pattern.label_expression, LabelDisjunction)


def test_node_wraps_a_plain_string_in_a_label_name():
    pattern = node("Movie")

    assert isinstance(pattern.label_expression, LabelName)


def test_node_pattern_rejects_a_non_term_field():
    with pytest.raises(DslError):
        NodePattern(label_expression="Movie")  # type: ignore[arg-type]


def test_with_labels_extends_plain_labels_only():
    base = node("Person")
    extended = base.with_labels("Actor", "Director", "Actor")

    assert isinstance(extended.label_expression, ColonConjunction)
    assert [term.name.value for term in extended.label_expression.terms] == ["Person", "Actor", "Director"]

    with pytest.raises(DslError):
        node(label("A") | label("B")).with_labels("C")


def test_relationship_factory_accepts_a_type_expression():
    chain = node("Person", name="p").relationship_to(node("Movie"), label("ACTED_IN") | label("DIRECTED"))

    relationship = chain.relationships[0]
    assert isinstance(relationship.type_expression, LabelDisjunction)


def test_relationship_factory_wraps_a_plain_string():
    chain = node("Person").relationship_to(node("Movie"), "ACTED_IN")

    assert isinstance(chain.relationships[0].type_expression, LabelName)


def test_relationship_rejects_a_colon_conjunction_type():
    conjunction = ColonConjunction((label("A"), label("B")))
    with pytest.raises(DslError):
        node("Person").relationship_to(node("Movie"), conjunction)


def test_relationship_factory_rejects_other_types():
    with pytest.raises(DslError):
        node("Person").relationship_to(node("Movie"), 42)  # type: ignore[arg-type]


def test_relationship_direct_construction_does_not_coerce_a_string():
    with pytest.raises(DslError):
        Relationship(
            node("Person"),
            node("Movie"),
            RelationshipDirection.OUTGOING,
            "ACTED_IN",  # type: ignore[arg-type]
        )


def test_relationship_direct_construction_rejects_the_old_symbolic_name_field():
    with pytest.raises(DslError, match="label expression"):
        Relationship(
            node("Person"),
            node("Movie"),
            RelationshipDirection.OUTGOING,
            SymbolicName("ACTED_IN"),  # type: ignore[arg-type]
        )


def test_relationship_rejects_a_nested_colon_conjunction_type():
    nested = node("A").with_labels("B").label_expression | label("C")

    with pytest.raises(DslError, match="exactly one type"):
        node("Person").relationship_to(node("Movie"), nested)


def test_create_rejects_a_label_expression():
    with pytest.raises(DslError, match="CREATE accepts plain labels"):
        create(node(label("Movie") | label("Person")))


def test_merge_rejects_a_label_expression():
    with pytest.raises(DslError, match="MERGE accepts plain labels"):
        merge(node(~label("Person")))


def test_create_rejects_a_type_expression():
    with pytest.raises(DslError, match="CREATE accepts one plain relationship type"):
        create(node("Person").relationship_to(node("Movie"), label("R") | label("S")))


def test_merge_rejects_a_type_expression():
    with pytest.raises(DslError, match="MERGE accepts one plain relationship type"):
        merge(node("Person").relationship_to(node("Movie"), ANY_LABEL))


def test_write_clauses_accept_plain_labels():
    statement = create(node("Person", name="p").with_labels("Employee"))

    rendered = Renderer.get(Configuration(server_version="5.26")).render(statement).cypher
    assert rendered == "CREATE (p:Person:Employee)"


def test_merge_accepts_plain_labels():
    statement = merge(node("Person", name="p").with_labels("Employee"))

    rendered = Renderer.get(Configuration(server_version="5.26")).render(statement).cypher
    assert rendered == "MERGE (p:Person:Employee)"


def test_with_labels_collapses_a_fully_duplicated_call():
    pattern = node("Person", name="p").with_labels("Person")

    assert isinstance(pattern.label_expression, LabelName)
    rendered = Renderer.get(Configuration(server_version="5.26")).render(create(pattern)).cypher
    assert rendered == "CREATE (p:Person)"


def test_node_rejects_a_colon_list_below_the_root():
    with pytest.raises(DslError, match="colon list is the whole label expression"):
        NodePattern(node("A").with_labels("B").label_expression & label("C"))


def test_node_rejects_a_negated_colon_list():
    with pytest.raises(DslError, match="colon list is the whole label expression"):
        NodePattern(~(node("A").with_labels("B").label_expression))

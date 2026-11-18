"""Direct syntax constructors cannot retain caller-owned mutable containers."""

import pytest

from cypher_dsl import (
    Configuration,
    CreateClause,
    DeleteClause,
    FunctionInvocation,
    LabelUpdate,
    ListExpression,
    MapExpression,
    MatchClause,
    MergeAction,
    MergeClause,
    NodePattern,
    PatternProperties,
    RelationshipPattern,
    RemoveClause,
    Renderer,
    ReturnClause,
    SetClause,
    Statement,
    StatementBuilder,
    SymbolicName,
    UnionStatement,
    WithClause,
    assign,
    lit,
    name,
    node,
)
from cypher_dsl.errors import DslError
from cypher_dsl.patterns.labels import LabelName


@pytest.mark.parametrize(
    "construct",
    [
        lambda values: StatementBuilder(values),
        lambda values: Statement(values),
        lambda values: UnionStatement(values),
        lambda values: MatchClause(values),
        lambda values: FunctionInvocation(values, (lit(1),)),
        lambda values: FunctionInvocation(("coalesce",), values),
        lambda values: PatternProperties(values),
        lambda values: PatternProperties((values,)),
        lambda values: RelationshipPattern(values),
        lambda values: ReturnClause(values),
        lambda values: WithClause((name("p"),), order_by=values),
        lambda values: ListExpression(values),
        lambda values: MapExpression(values),
        lambda values: MapExpression((values,)),
        lambda values: CreateClause(values),
        lambda values: MergeClause(node("Person"), values),
        lambda values: MergeAction("ON CREATE", values),
        lambda values: SetClause(values),
        lambda values: RemoveClause(values),
        lambda values: DeleteClause(values),
        lambda values: LabelUpdate(name("p"), values),
    ],
)
def test_public_syntax_collections_reject_caller_owned_lists(construct):
    with pytest.raises(DslError, match=r"tuple|pair"):
        construct([])


def test_a_node_pattern_label_position_holds_a_term_not_a_collection():
    with pytest.raises(DslError, match="LabelExpression"):
        NodePattern([])  # type: ignore[arg-type]


def test_rejected_statement_list_cannot_change_a_finalised_statement():
    clauses = [ReturnClause((lit(1),))]
    with pytest.raises(DslError, match="tuple"):
        Statement(clauses)
    statement = Statement(tuple(clauses))
    clauses.append(CreateClause((node("Person", name="p"),)))
    assert Renderer.get(Configuration(server_version="5.26")).render(statement).cypher == "RETURN 1"


def test_rejected_nested_lists_cannot_change_a_finalised_statement():
    arguments = [lit(1)]
    patterns = [node("Person", name="p")]
    with pytest.raises(DslError, match="tuple"):
        FunctionInvocation(("coalesce",), arguments)
    with pytest.raises(DslError, match="tuple"):
        MatchClause(patterns)
    statement = Statement(
        (MatchClause(tuple(patterns)), ReturnClause((FunctionInvocation(("coalesce",), tuple(arguments)),)))
    )
    arguments.append(lit(2))
    patterns.clear()
    assert (
        Renderer.get(Configuration(server_version="5.26")).render(statement).cypher
        == "MATCH (p:Person) RETURN coalesce(1)"
    )


def test_rejected_pattern_entry_list_cannot_change_finalised_properties():
    entry = [SymbolicName("uid"), lit(1)]
    with pytest.raises(DslError, match=r"tuple|pair"):
        PatternProperties((entry,))
    person = NodePattern(LabelName(SymbolicName("Person")), SymbolicName("p"), PatternProperties((tuple(entry),)))
    statement = Statement((CreateClause((person,)), SetClause((assign(person["active"], True),))))
    entry[1] = lit(2)
    assert Renderer.get(Configuration(server_version="5.26")).render(statement).cypher == (
        "CREATE (p:Person {uid: 1}) SET p.`active` = true"
    )

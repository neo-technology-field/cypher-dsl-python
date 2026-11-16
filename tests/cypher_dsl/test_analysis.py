from cypher_dsl import assign, asterisk, create, match, merge, name, node, param, raw, returning, union
from cypher_dsl.features import Capability
from cypher_dsl.statements.analysis import NodePatternFacts, analyse
from cypher_dsl.statements.scope import DeclarationRole


def test_same_node_pattern_object_gets_facts_by_occurrence_path() -> None:
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    statement = match(person).with_("p").create(movie.relationship_from(person, "ACTED_IN")).build()
    analysis = analyse(statement)
    roles = [facts.role for _, facts in sorted(analysis.facts.items()) if isinstance(facts, NodePatternFacts)]
    assert roles == [DeclarationRole.DECLARE, DeclarationRole.DECLARE, DeclarationRole.REFERENCE]


def test_with_wildcard_retains_a_node_declaration_for_a_write_endpoint() -> None:
    person = node("Person", name="p")
    statement = match(person).with_(asterisk()).create(person.relationship_to(node("Movie"), "ACTED_IN")).build()
    analysis = analyse(statement)

    assert analysis.facts_for((0, 0)) == NodePatternFacts(DeclarationRole.DECLARE)
    assert analysis.facts_for((2, 0, 0)) == NodePatternFacts(DeclarationRole.REFERENCE)
    assert analysis.facts_for((2, 0, 1, 0)) == NodePatternFacts(DeclarationRole.DECLARE)


def test_raw_with_retains_known_node_declarations_for_write_endpoints() -> None:
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    statement = match(person).with_(raw("p")).create(person.relationship_to(movie, "ACTED_IN")).build()
    analysis = analyse(statement)

    assert analysis.facts_for((0, 0)) == NodePatternFacts(DeclarationRole.DECLARE)
    assert analysis.facts_for((2, 0, 0)) == NodePatternFacts(DeclarationRole.REFERENCE)
    assert analysis.facts_for((2, 0, 1, 0)) == NodePatternFacts(DeclarationRole.DECLARE)


def test_with_wildcard_does_not_treat_a_new_write_endpoint_as_a_reference() -> None:
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    statement = match(person).with_(asterisk()).create(movie.relationship_to(node("Person"), "LIKES")).build()
    analysis = analyse(statement)

    assert analysis.facts_for((2, 0, 0)) == NodePatternFacts(DeclarationRole.DECLARE)
    assert analysis.facts_for((2, 0, 1, 0)) == NodePatternFacts(DeclarationRole.DECLARE)


def test_non_wildcard_with_drops_node_declarations_it_does_not_project() -> None:
    person = node("Person", name="p")
    other = node("Person", name="q")
    movie = node("Movie", name="m")
    statement = match(person, other).with_(person).create(other.relationship_to(movie, "LIKES")).build()
    analysis = analyse(statement)

    assert analysis.facts_for((0, 1)) == NodePatternFacts(DeclarationRole.DECLARE)
    assert analysis.facts_for((2, 0, 0)) == NodePatternFacts(DeclarationRole.DECLARE)
    assert analysis.facts_for((2, 0, 1, 0)) == NodePatternFacts(DeclarationRole.DECLARE)


def test_shared_node_self_loop_uses_each_occurrences_declaration_role() -> None:
    person = node("Person", name="p")
    analysis = analyse(create(person.relationship_to(person, "KNOWS")).build())

    assert analysis.facts_for((0, 0, 0)) == NodePatternFacts(DeclarationRole.DECLARE)
    assert analysis.facts_for((0, 0, 1, 0)) == NodePatternFacts(DeclarationRole.REFERENCE)


def test_anonymous_create_node_is_a_declaration() -> None:
    analysis = analyse(create(node("Movie")).build())

    assert analysis.facts_for((0, 0)) == NodePatternFacts(DeclarationRole.DECLARE)


def test_anonymous_merge_node_is_a_declaration() -> None:
    analysis = analyse(merge(node("Movie")).build())

    assert analysis.facts_for((0, 0)) == NodePatternFacts(DeclarationRole.DECLARE)


def test_anonymous_write_endpoint_and_named_start_are_declarations() -> None:
    person = node("Person", name="p")
    analysis = analyse(create(person.relationship_to(node("Movie"), "ACTED_IN")).build())

    assert analysis.facts_for((0, 0, 0)) == NodePatternFacts(DeclarationRole.DECLARE)
    assert analysis.facts_for((0, 0, 1, 0)) == NodePatternFacts(DeclarationRole.DECLARE)


def test_anonymous_write_pattern_does_not_consume_named_declarations() -> None:
    analysis = analyse(create(node("Movie"), node("Person", name="p"), node("Actor", name="a")).build())

    assert analysis.facts_for((0, 0)) == NodePatternFacts(DeclarationRole.DECLARE)
    assert analysis.facts_for((0, 1)) == NodePatternFacts(DeclarationRole.DECLARE)
    assert analysis.facts_for((0, 2)) == NodePatternFacts(DeclarationRole.DECLARE)


def test_match_node_is_a_declaration_even_when_the_name_appeared_before() -> None:
    person = node("Person", name="p")
    analysis = analyse(match(person).with_("p").match(person).returning("p").build())
    roles = [facts.role for facts in analysis.facts.values() if isinstance(facts, NodePatternFacts)]
    assert roles == [DeclarationRole.DECLARE, DeclarationRole.DECLARE]


def test_dynamic_property_writes_are_recorded_only_for_update_targets() -> None:
    row = name("row")
    write = match(node("Row", name="row")).set_(assign(row[param("key")], 1)).build()
    analysis = analyse(write)
    assert [(requirement.capability, requirement.path) for requirement in analysis.requirements] == [
        (Capability.DYNAMIC_PROPERTY_WRITES, (1, 0, 0))
    ]

    read = returning(row[param("key")]).build()
    assert analyse(read).requirements == ()

    read_in_write = match(node("Row", name="row")).set_(assign(name("x"), row[param("key")])).build()
    assert analyse(read_in_write).requirements == ()


def test_merge_actions_and_remove_record_dynamic_writes() -> None:
    target = node("Target", name="t")
    merged = merge(target).on_create(assign(target[name("k")], 1)).build()
    removed = match(target).remove(target[name("old")]).build()
    assert [requirement.capability for requirement in analyse(merged).requirements] == [
        Capability.DYNAMIC_PROPERTY_WRITES
    ]
    assert [requirement.capability for requirement in analyse(removed).requirements] == [
        Capability.DYNAMIC_PROPERTY_WRITES
    ]


def test_parameters_are_reported_in_existing_traversal_order() -> None:
    statement = returning(param("b", 2), param("a"), param("b", 2)).build()
    assert [parameter.symbol.value for parameter in analyse(statement).parameters] == ["b", "a", "b"]


def test_union_branches_have_isolated_scope_facts() -> None:
    left = match(node("Person", name="p")).returning("p").build()
    right = create(node("Person", name="p")).returning("p").build()
    analysis = analyse(union(left, right))
    roles = [facts.role for facts in analysis.facts.values() if isinstance(facts, NodePatternFacts)]
    assert roles == [DeclarationRole.DECLARE, DeclarationRole.DECLARE]

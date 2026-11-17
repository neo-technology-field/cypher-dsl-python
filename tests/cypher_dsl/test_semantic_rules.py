"""Semantic rules exercised through the registry, independently of the walker."""

from __future__ import annotations

import pytest

from cypher_dsl import match, name, node
from cypher_dsl.errors import DslError
from cypher_dsl.statements.frames import ScopeFrame
from cypher_dsl.statements.rules import MatchRule, semantic_rules


def test_match_binds_pattern_names_and_declarations() -> None:
    person = node("Person", name="p")
    frame = MatchRule().bindings(ScopeFrame(("t",)), match(person).clauses[0])
    assert frame.names == ("t", "p")
    assert frame.bindings[0][0] == "p"
    assert frame.closed is False


def test_match_rejects_an_unbound_property_reference_in_a_closed_frame() -> None:
    clause = match(node("Movie", properties={"title": name("q")["name"]})).clauses[0]
    with pytest.raises(DslError, match="which is not in scope"):
        MatchRule().validate(clause, ScopeFrame(("p",), closed=True))


def test_match_tolerates_unknown_references_in_an_open_frame() -> None:
    clause = match(node("Movie", properties={"title": name("q")["name"]})).clauses[0]
    MatchRule().validate(clause, ScopeFrame(("p",)))


def test_match_cannot_rebind_a_discarded_reserved_name() -> None:
    clause = match(node("Person", name="p")).clauses[0]
    frame = ScopeFrame((), closed=True, reserved=frozenset({"p"}))
    with pytest.raises(DslError, match="redeclares imported name 'p'"):
        MatchRule().validate(clause, frame)


def test_match_may_reference_a_kept_reserved_name_with_other_filters() -> None:
    clause = match(node("Movie", name="p")).clauses[0]
    MatchRule().validate(clause, ScopeFrame(("p",), closed=True, reserved=frozenset({"p"})))


def test_registry_resolves_registered_and_unregistered_nodes() -> None:
    rules = semantic_rules()
    statement = match(node("Person", name="p")).returning(name("p")).build()
    assert isinstance(rules.resolve(statement.clauses[0]), MatchRule)


def test_registry_find_uses_the_nearest_registered_class_or_returns_none() -> None:
    from cypher_dsl.expressions.base import Expression
    from cypher_dsl.statements.rules import SemanticRule, SemanticRules
    from cypher_dsl.ast import AstNode

    class MarkerExpression(Expression):
        __slots__ = ()

    class DerivedMarkerExpression(MarkerExpression):
        __slots__ = ()

    fallback = SemanticRule()
    marker = SemanticRule()
    rules = SemanticRules({Expression: fallback, MarkerExpression: marker})
    assert rules.find(MarkerExpression()) is marker
    assert rules.find(DerivedMarkerExpression()) is marker
    assert rules.find(name("p")) is fallback
    assert rules.find(AstNode()) is None


@pytest.mark.parametrize("certified", [False, True])
def test_with_closes_the_frame_and_inherits_certification(certified: bool) -> None:
    from cypher_dsl import with_

    person = node("Person", name="p")
    clause = with_(person).clauses[0]
    from cypher_dsl.statements.rules import semantic_rules

    rule = semantic_rules().resolve(clause)
    after = rule.bindings(ScopeFrame(("p", "m"), certified=certified, reserved=frozenset({"p"})), clause)
    assert after.names == ("p",)
    assert after.closed is True
    assert after.certified is certified
    assert after.reserved == frozenset({"p"})


def test_with_cannot_rebind_a_reserved_name_to_another_expression() -> None:
    from cypher_dsl import lit, with_

    clause = with_(lit("New team").alias("t")).clauses[0]
    frame = ScopeFrame((), closed=True, certified=True, reserved=frozenset({"t"}))
    from cypher_dsl.statements.rules import semantic_rules

    with pytest.raises(DslError, match="redeclares imported name 't' in WITH"):
        semantic_rules().resolve(clause).validate(clause, frame)


def test_return_accepts_a_projected_imported_name_in_a_called_body() -> None:
    from cypher_dsl import lit, returning

    clause = returning(lit(1).alias("p"), lit(2).alias("x")).clauses[0]
    frame = ScopeFrame(("p",), closed=True, certified=True, reserved=frozenset({"p"}))
    from cypher_dsl.statements.rules import semantic_rules

    semantic_rules().resolve(clause).validate(clause, frame)


def test_unwind_binds_its_variable_and_checks_reserved() -> None:
    from cypher_dsl import unwind

    clause = unwind([1], name("row")).clauses[0]
    from cypher_dsl.statements.rules import semantic_rules

    rule = semantic_rules().resolve(clause)
    after = rule.bindings(ScopeFrame(()), clause)
    assert after.names == ("row",)
    with pytest.raises(DslError, match="redeclares imported name 'row'"):
        rule.validate(clause, ScopeFrame(("row",), closed=True, reserved=frozenset({"row"})))


def test_union_columns_use_the_seeded_frame() -> None:
    from cypher_dsl import asterisk, lit, returning
    from cypher_dsl.statements.rules.flow import union_columns_check

    parts = (returning(asterisk()).build(), returning(lit(1).alias("one"), lit(2).alias("two")).build())
    with pytest.raises(DslError, match="UNION branches project 1 and 2 columns"):
        union_columns_check(parts, ScopeFrame(("p",), closed=True, certified=True))


def test_write_endpoint_without_identity_follows_the_deferral_set() -> None:
    from cypher_dsl.statements.rules.writes import classify_write_declarations

    person = node("Person", name="p")
    pattern = person.relationship_to(node("Clone"), "COPIED_AS")
    classify_write_declarations(ScopeFrame(None), (pattern,), "CREATE")
    with pytest.raises(DslError, match="conflicting declaration"):
        classify_write_declarations(ScopeFrame(("p",)), (pattern,), "CREATE")
    classify_write_declarations(ScopeFrame(("p",), unresolved=frozenset({"p"})), (pattern,), "CREATE")


def test_call_enter_body_seeds_imports_and_reserved() -> None:
    from cypher_dsl.clauses.call import SubqueryCallClause
    from cypher_dsl.statements.rules.call import CallRule

    person = node("Person", name="p")
    body = match(node("Movie", name="m")).returning(name("m")).build()
    clause = SubqueryCallClause(body, (name("p"),))
    seed = CallRule().enter_body(ScopeFrame(("p", "t"), bindings=(("p", person),)), clause)
    assert seed.names == ("p",)
    assert seed.closed is True
    assert seed.certified is False
    assert seed.reserved == frozenset({"p"})
    assert seed.bindings[0][0] == "p"
    assert seed.bindings[0][1] is person
    empty = CallRule().enter_body(ScopeFrame(("p", "t")), SubqueryCallClause(body, ()))
    assert empty.names == ()
    assert empty.certified is True


def test_call_wildcard_seeds_only_from_closed_or_certified_frames() -> None:
    from cypher_dsl.clauses.call import SubqueryCallClause
    from cypher_dsl.statements.rules.call import CallRule

    body = match(node("Movie", name="m")).returning(name("m")).build()
    clause = SubqueryCallClause(body, (), import_all=True)
    seed = CallRule().enter_body(ScopeFrame(("p",)), clause)
    assert seed.names is None
    closed = CallRule().enter_body(ScopeFrame(("p",), closed=True), clause)
    assert closed.names == ("p",)
    certified = CallRule().enter_body(ScopeFrame(("p",), certified=True), clause)
    assert certified.names == ("p",)
    unknown = CallRule().enter_body(ScopeFrame(None, closed=True, certified=True), clause)
    assert unknown.names is None


def test_call_named_import_defers_an_endpoint_identity_until_attachment() -> None:
    from cypher_dsl import create
    from cypher_dsl.clauses.call import SubqueryCallClause
    from cypher_dsl.statements.rules.call import CallRule
    from cypher_dsl.statements.rules.writes import classify_write_declarations

    person = node("Person", name="p")
    pattern = person.relationship_to(node("Clone"), "COPIED_AS")
    clause = SubqueryCallClause(create(pattern).build(), (name("p"),))
    seed = CallRule().enter_body(ScopeFrame(()), clause)
    assert seed.unresolved == frozenset({"p"})
    classify_write_declarations(seed, (pattern,), "CREATE")


def test_call_wildcard_defers_imports_from_an_empty_construction_frame() -> None:
    from cypher_dsl import create
    from cypher_dsl.clauses.call import SubqueryCallClause
    from cypher_dsl.statements.rules.call import CallRule

    clause = SubqueryCallClause(create(node("Person")).build(), import_all=True)
    seed = CallRule().enter_body(ScopeFrame(()), clause)
    assert seed.names is None


def test_write_rejects_a_relationship_name_reused_as_an_endpoint_in_an_unknown_frame() -> None:
    from cypher_dsl.statements.rules.writes import classify_write_declarations

    first = node("Left", name="a").relationship_to(node("Right", name="b"), "LINK", name="r")
    second = node("Left", name="r").relationship_to(node("Clone"), "LINK")
    with pytest.raises(DslError, match="conflicting declaration for bound endpoint 'r'"):
        classify_write_declarations(ScopeFrame(None), (first, second), "CREATE")


def test_call_import_existence_follows_certification() -> None:
    from cypher_dsl.clauses.call import SubqueryCallClause
    from cypher_dsl.statements.rules.call import CallRule

    body = match(node("Movie", name="m")).returning(name("m")).build()
    clause = SubqueryCallClause(body, (name("p"), name("t")))
    CallRule().validate(clause, ScopeFrame(("p",)))
    with pytest.raises(DslError, match="imports 't', which is not in scope"):
        CallRule().validate(clause, ScopeFrame(("p",), certified=True))


def test_reserved_names_survive_an_inner_with() -> None:
    from cypher_dsl import lit, with_
    from cypher_dsl.clauses.call import SubqueryCallClause
    from cypher_dsl.statements.rules import walk_clauses
    from cypher_dsl.statements.rules.call import CallRule

    body = with_(lit(1).alias("one")).unwind([1], name("p")).returning(name("one")).build()
    clause = SubqueryCallClause(body, (name("p"),))
    seed = CallRule().enter_body(ScopeFrame(("p",)), clause)
    with pytest.raises(DslError, match="redeclares imported name 'p'"):
        walk_clauses(body.clauses, seed)


def test_unknown_names_stay_uncertified() -> None:
    from cypher_dsl import raw, with_
    from cypher_dsl.clauses.call import SubqueryCallClause
    from cypher_dsl.statements.frames import is_unresolved_node
    from cypher_dsl.statements.rules import frame_after, walk_clauses
    from cypher_dsl.statements.rules.call import CallRule

    person = node("Person", name="p")
    body = with_(name("p")).create(person.relationship_to(node("Clone"), "COPIED_AS")).build()
    prefix = with_(name("p")).with_(raw("p"))
    frame = frame_after(prefix.clauses)
    assert frame.names is None
    assert frame.closed is True
    assert frame.certified is False
    clause = SubqueryCallClause(body, (), import_all=True)
    seed = CallRule().enter_body(frame, clause)
    assert seed.names is None
    assert seed.certified is False
    assert seed.unresolved == frozenset()
    assert is_unresolved_node(seed, "p") is True
    projected = frame_after(body.clauses[:1], seed)
    assert projected.unresolved == frozenset({"p"})
    walk_clauses(body.clauses, seed)


def test_every_clause_class_has_a_semantic_rule() -> None:
    import importlib
    import inspect
    import pkgutil

    import cypher_dsl.clauses
    from cypher_dsl import assign, create, lit, merge, returning, unwind, with_
    from cypher_dsl.clauses.base import Clause
    from cypher_dsl.clauses.call import SubqueryCallClause
    from cypher_dsl.clauses.match import MatchClause
    from cypher_dsl.clauses.projection import ProjectionClause, ReturnClause, WithClause
    from cypher_dsl.clauses.unwind import UnwindClause
    from cypher_dsl.clauses.write import CreateClause, DeleteClause, MergeClause, RemoveClause, SetClause
    from cypher_dsl.errors import UnsupportedFeatureError

    rules = semantic_rules()
    person = node("Person", name="p")
    body = returning(lit(1).alias("one")).build()
    statements = (
        match(person).returning(person).build(),
        with_(name("p")).returning(name("p")).build(),
        unwind([1], name("row")).returning(name("row")).build(),
        create(person).build(),
        merge(person).on_create(assign(person["uid"], "p1")).build(),
        match(person).set_(assign(person["uid"], "p1")).build(),
        match(person).remove(person["uid"]).build(),
        match(person).delete(person).build(),
        match(person).call(body, imports=("p",)).returning(name("one")).build(),
    )
    seen: set[type[Clause]] = set()
    for statement in statements:
        for clause in statement.clauses:
            seen.add(type(clause))
            rules.resolve(clause)
    assert seen == {
        MatchClause,
        WithClause,
        ReturnClause,
        UnwindClause,
        CreateClause,
        MergeClause,
        SetClause,
        RemoveClause,
        DeleteClause,
        SubqueryCallClause,
    }

    discovered: set[type[Clause]] = set()
    for module_info in pkgutil.walk_packages(cypher_dsl.clauses.__path__, cypher_dsl.clauses.__name__ + "."):
        module = importlib.import_module(module_info.name)
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if (
                cls.__module__ == module.__name__
                and issubclass(cls, Clause)
                and cls not in (Clause, ProjectionClause)
                and not inspect.isabstract(cls)
            ):
                discovered.add(cls)
                assert rules.resolve(cls.__new__(cls)) is not None
    assert seen <= discovered

    class UnregisteredClause(Clause):
        __slots__ = ()

    with pytest.raises(UnsupportedFeatureError):
        rules.resolve(UnregisteredClause())


@pytest.mark.parametrize("nested", [False, True])
def test_analysis_dispatches_expression_validation_and_recording(monkeypatch: pytest.MonkeyPatch, nested: bool) -> None:
    from cypher_dsl import call, lit, with_
    from cypher_dsl.expressions.base import Expression
    from cypher_dsl.features import Capability
    from cypher_dsl.statements.analysis import analyse
    from cypher_dsl.statements.rules import SemanticRule, SemanticRules, shared_rules
    from cypher_dsl.statements.rules import base as rule_base
    from cypher_dsl.statements.rules.base import AnalysisSink
    from cypher_dsl.ast import AstNode

    class MarkerExpression(Expression):
        __slots__ = ()

    validated: list[ScopeFrame] = []

    class MarkerRule(SemanticRule):
        def validate(self, node: AstNode, frame: ScopeFrame) -> None:
            validated.append(frame)

        def record(self, node: AstNode, frame: ScopeFrame, sink: AnalysisSink) -> None:
            sink.requirement(Capability.SCOPE_CLAUSES)

        def bindings(self, frame: ScopeFrame, node: AstNode) -> ScopeFrame:
            raise AssertionError("Expression rules must not advance clause frames.")

    statement = with_(lit(1).alias("p")).returning(MarkerExpression()).build()
    if nested:
        statement = call(statement).returning(lit(1)).build()
    rules = shared_rules()
    rules[MarkerExpression] = MarkerRule()
    monkeypatch.setattr(rule_base, "_RULES", SemanticRules(rules))

    analysis = analyse(statement)

    assert len(validated) == 1
    assert validated[0].names == ("p",)
    assert validated[0].closed is True
    assert validated[0].certified is True
    expected = (
        [(Capability.SCOPE_CLAUSES, (0,)), (Capability.SCOPE_CLAUSES, (0, 0, 1, 0))]
        if nested
        else [(Capability.SCOPE_CLAUSES, (1, 0))]
    )
    assert [(item.capability, item.path) for item in analysis.requirements] == expected


def test_analysis_validates_each_nested_body_projection_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from collections import Counter

    from cypher_dsl import call, lit, returning
    from cypher_dsl.clauses.projection import ProjectionClause, ReturnClause
    from cypher_dsl.expressions.values import AliasedExpression
    from cypher_dsl.statements.analysis import analyse
    from cypher_dsl.statements.rules import ProjectionRule, SemanticRules, shared_rules
    from cypher_dsl.statements.rules import base as rule_base

    statement = returning(lit(1).alias("level4")).build()
    for level in range(3, -1, -1):
        statement = call(statement).returning(lit(1).alias(f"level{level}")).build()
    validations: Counter[str] = Counter()

    class CountingProjectionRule(ProjectionRule):
        def validate(self, node: ProjectionClause, frame: ScopeFrame) -> None:
            super().validate(node, frame)
            expression = node.expressions[0]
            assert isinstance(expression, AliasedExpression)
            validations[expression.alias_name.value] += 1

    rules = shared_rules()
    rules[ReturnClause] = CountingProjectionRule()
    monkeypatch.setattr(rule_base, "_RULES", SemanticRules(rules))

    analyse(statement)

    assert validations == {"level0": 1, "level1": 1, "level2": 1, "level3": 1, "level4": 1}


@pytest.mark.parametrize("keyword", ["CREATE", "MERGE"])
def test_pattern_writes_keep_frame_flags_and_known_node_identity(keyword: str) -> None:
    from cypher_dsl.clauses.write import CreateClause, MergeClause
    from cypher_dsl.statements.rules.writes import CreateRule, MergeRule

    person = node("Person", name="p")
    clone = node("Clone", name="c")
    pattern = person.relationship_to(clone, "COPIED_AS", name="r")
    clause = CreateClause((pattern,)) if keyword == "CREATE" else MergeClause(pattern)
    rule = CreateRule() if keyword == "CREATE" else MergeRule()
    original = node("Person", name="p")
    frame = ScopeFrame(("p",), True, True, frozenset({"p"}), (("p", original),))
    rule.validate(clause, frame)
    after = rule.bindings(frame, clause)
    assert after.names == ("p", "c", "r")
    assert after.closed is True
    assert after.certified is True
    assert after.reserved == frozenset({"p"})
    assert dict(after.bindings)["p"] is original
    assert dict(after.bindings)["c"] is clone
    assert frame.names == ("p",)
    assert rule.bindings(ScopeFrame(None), clause).names is None


def test_write_roles_distinguish_reused_node_occurrences_and_anonymous_nodes() -> None:
    from cypher_dsl.clauses.write import CreateClause
    from cypher_dsl.statements.frames import DeclarationRole
    from cypher_dsl.statements.rules.base import PatternState
    from cypher_dsl.statements.rules.writes import CreateRule

    person = node("Person", name="p")
    anonymous = node("Clone")
    clause = CreateClause((person.relationship_to(person, "COPIED_AS"), anonymous))
    rule = CreateRule()
    state = PatternState()
    assert rule.pattern_role(clause, person, ScopeFrame(), state) is DeclarationRole.DECLARE
    assert rule.pattern_role(clause, person, ScopeFrame(), state) is DeclarationRole.REFERENCE
    assert rule.pattern_role(clause, anonymous, ScopeFrame(), state) is DeclarationRole.DECLARE


def test_write_property_references_exclude_bound_node_properties() -> None:
    from cypher_dsl.statements.frames import DeclarationRole
    from cypher_dsl.statements.rules.writes import classify_write_declarations, write_property_references

    person = node("Person", name="p", properties={"uid": name("external")})
    clone = node("Clone", properties={"uid": name("copied")})
    pattern = person.relationship_to(clone, "COPIED_AS", properties={"uid": name("link")})
    declarations = classify_write_declarations(ScopeFrame(("p",), bindings=(("p", person),)), (pattern,), "CREATE")
    assert declarations[0].role is DeclarationRole.REFERENCE
    assert tuple(variable.symbol.value for variable in write_property_references((pattern,), declarations)) == (
        "copied",
        "link",
    )


@pytest.mark.parametrize("keyword", ["CREATE", "MERGE"])
def test_pattern_writes_reject_unknown_property_references_in_closed_frames(keyword: str) -> None:
    from cypher_dsl.clauses.write import CreateClause, MergeClause
    from cypher_dsl.statements.rules.writes import CreateRule, MergeRule

    person = node("Person", name="p", properties={"uid": name("q")})
    clause = CreateClause((person,)) if keyword == "CREATE" else MergeClause(person)
    rule = CreateRule() if keyword == "CREATE" else MergeRule()
    rule.validate(clause, ScopeFrame())
    with pytest.raises(DslError, match=f"{keyword} pattern properties refers to 'q'"):
        rule.validate(clause, ScopeFrame((), closed=True))


@pytest.mark.parametrize("keyword", ["ON CREATE", "ON MATCH"])
def test_merge_actions_check_both_update_targets_and_values(keyword: str) -> None:
    from cypher_dsl import assign
    from cypher_dsl.clauses.write import MergeAction, MergeClause
    from cypher_dsl.statements.rules.writes import MergeRule

    person = node("Person", name="p")
    for update in (assign(person["uid"], name("q")), assign(name("q")["uid"], 1)):
        clause = MergeClause(person, (MergeAction(keyword, (update,)),))
        MergeRule().validate(clause, ScopeFrame())
        with pytest.raises(DslError, match=f"{keyword} refers to 'q'"):
            MergeRule().validate(clause, ScopeFrame((), closed=True))


@pytest.mark.parametrize("keyword", ["SET", "REMOVE", "DELETE"])
def test_target_writes_check_references_without_changing_bindings(keyword: str) -> None:
    from cypher_dsl import assign
    from cypher_dsl.clauses.write import DeleteClause, RemoveClause, SetClause

    clauses = {
        "SET": SetClause((assign(name("q")["uid"], 1),)),
        "REMOVE": RemoveClause((name("q")["uid"],)),
        "DELETE": DeleteClause((name("q"),)),
    }
    clause = clauses[keyword]
    rule = semantic_rules().resolve(clause)
    frame = ScopeFrame(("p",), closed=True)
    assert rule.bindings(frame, clause) is frame
    rule.validate(clause, ScopeFrame())
    with pytest.raises(DslError, match=f"{keyword} refers to 'q'"):
        rule.validate(clause, frame)


def test_dynamic_property_writes_record_target_occurrence_paths() -> None:
    from cypher_dsl import assign, set_labels
    from cypher_dsl.clauses.write import RemoveClause, SetClause
    from cypher_dsl.features import Capability
    from cypher_dsl.statements.frames import SyntaxRequirement
    from cypher_dsl.statements.rules.base import AnalysisSink

    dynamic = name("p")[name("key")]
    clauses = (
        SetClause((set_labels(name("p"), "Person"), assign(dynamic, 1), assign(name("p")["uid"], 2))),
        RemoveClause((name("p")["uid"], dynamic)),
    )
    requirements: list[SyntaxRequirement] = []
    for index, clause in enumerate(clauses):
        sink = AnalysisSink({}, requirements, (3, index))
        assert sink.path == (3, index)
        semantic_rules().resolve(clause).record(clause, ScopeFrame(), sink)
    assert [(item.capability, item.path) for item in requirements] == [
        (Capability.DYNAMIC_PROPERTY_WRITES, (3, 0, 1, 0)),
        (Capability.DYNAMIC_PROPERTY_WRITES, (3, 1, 1)),
    ]


def test_merge_actions_record_dynamic_property_target_occurrence_paths() -> None:
    from cypher_dsl import assign
    from cypher_dsl.clauses.write import MergeAction, MergeClause
    from cypher_dsl.features import Capability
    from cypher_dsl.statements.frames import SyntaxRequirement
    from cypher_dsl.statements.rules.base import AnalysisSink
    from cypher_dsl.statements.rules.writes import MergeRule

    person = node("Person", name="p")
    dynamic = person[name("key")]
    clause = MergeClause(
        person,
        (
            MergeAction("ON CREATE", (assign(person["uid"], 1), assign(dynamic, 2))),
            MergeAction("ON MATCH", (assign(dynamic, 3),)),
        ),
    )
    requirements: list[SyntaxRequirement] = []
    MergeRule().record(clause, ScopeFrame(), AnalysisSink({}, requirements, (4, 3)))
    assert [(item.capability, item.path) for item in requirements] == [
        (Capability.DYNAMIC_PROPERTY_WRITES, (4, 3, 1, 1, 0)),
        (Capability.DYNAMIC_PROPERTY_WRITES, (4, 3, 2, 0, 0)),
    ]


def test_call_records_capabilities_at_the_call_occurrence() -> None:
    from cypher_dsl import create
    from cypher_dsl.clauses.call import SubqueryCallClause
    from cypher_dsl.features import Capability
    from cypher_dsl.statements.frames import SyntaxRequirement
    from cypher_dsl.statements.rules.base import AnalysisSink
    from cypher_dsl.statements.rules.call import CallRule

    clause = SubqueryCallClause(create(node("Person")).build(), optional=True, in_transactions=True)
    requirements: list[SyntaxRequirement] = []
    CallRule().record(clause, ScopeFrame(), AnalysisSink({}, requirements, (2, 1)))
    assert [(item.capability, item.path) for item in requirements] == [
        (Capability.SCOPE_CLAUSES, (2, 1)),
        (Capability.OPTIONAL_CALL, (2, 1)),
        (Capability.IN_TRANSACTIONS, (2, 1)),
    ]


def test_call_bindings_add_outputs_but_not_unit_body_declarations() -> None:
    from cypher_dsl import create
    from cypher_dsl.clauses.call import SubqueryCallClause
    from cypher_dsl.statements.rules.call import CallRule

    person = node("Person", name="p")
    movie = node("Movie", name="m")
    frame = ScopeFrame(("p",), reserved=frozenset({"p"}), bindings=(("p", person),))
    rule = CallRule()
    returning = SubqueryCallClause(match(movie).returning(movie).build())
    after = rule.bindings(frame, returning)
    assert after.names == ("p", "m")
    assert dict(after.bindings)["p"] is person
    assert dict(after.bindings)["m"] is movie
    assert after.closed is False
    assert after.certified is False
    assert after.reserved == frame.reserved
    unit = SubqueryCallClause(create(movie).build())
    assert rule.bindings(frame, unit) == frame


@pytest.mark.parametrize("reserved", [False, True])
def test_call_rejects_outer_name_collisions_even_after_projection_discards_them(reserved: bool) -> None:
    from cypher_dsl import lit, returning
    from cypher_dsl.clauses.call import SubqueryCallClause
    from cypher_dsl.statements.rules.call import CallRule

    clause = SubqueryCallClause(returning(lit(1).alias("p")).build())
    frame = ScopeFrame((), reserved=frozenset({"p"})) if reserved else ScopeFrame(("p",))
    message = "redeclares imported name 'p'" if reserved else "returns 'p', which the outer query already holds"
    with pytest.raises(DslError, match=message):
        CallRule().validate(clause, frame)


def test_call_union_outputs_keep_only_compatible_node_identities() -> None:
    from cypher_dsl import union
    from cypher_dsl.statements.rules.call import output_scope

    person = node("Person", name="p")
    compatible = node("Person", name="q")
    different = node("Movie", name="q")
    first = match(person).returning(name("p").alias("result")).build()
    for other, keeps_identity in ((compatible, True), (different, False)):
        second = match(other).returning(name("q").alias("result")).build()
        output = output_scope(union(first, second), ScopeFrame())
        assert output.names == ("result",)
        assert ("result" in dict(output.bindings)) is keeps_identity


@pytest.mark.parametrize("keyword", ["MATCH", "CREATE", "MERGE"])
def test_pattern_bindings_discard_deferrals_only_for_recorded_node_identities(keyword: str) -> None:
    from cypher_dsl import create, merge

    person = node("Person", name="p")
    original = node("Person", name="existing")
    clause = {"MATCH": match(person), "CREATE": create(person), "MERGE": merge(person)}[keyword].clauses[0]
    frame = ScopeFrame(
        ("existing", "p", "q"),
        bindings=(("existing", original),),
        unresolved=frozenset({"existing", "p", "q"}),
    )
    after = semantic_rules().resolve(clause).bindings(frame, clause)
    assert after.unresolved == frozenset({"q"})
    assert frame.unresolved == frozenset({"existing", "p", "q"})


def test_unwind_keeps_deferred_node_identities_even_for_its_target_name() -> None:
    from cypher_dsl import unwind

    clause = unwind([1], name("p")).clauses[0]
    rule = semantic_rules().resolve(clause)
    for frame in (ScopeFrame(("p",), unresolved=frozenset({"p"})), ScopeFrame(None, unresolved=frozenset({"p"}))):
        assert rule.bindings(frame, clause).unresolved == frozenset({"p"})


def test_projections_retain_deferred_aliases_but_not_replacement_values() -> None:
    from cypher_dsl import asterisk, lit, raw, with_

    frame = ScopeFrame(("p", "q"), closed=True, certified=True, unresolved=frozenset({"p", "q"}))
    clause = with_(name("p").alias("kept"), lit(1).alias("p")).clauses[0]
    after = semantic_rules().resolve(clause).bindings(frame, clause)
    assert after.unresolved == frozenset({"kept"})
    for expression in (asterisk(), raw("p")):
        clause = with_(expression).clauses[0]
        assert semantic_rules().resolve(clause).bindings(frame, clause).unresolved == frozenset({"p", "q"})


def test_call_outputs_merge_deferred_aliases_and_unit_bodies_export_none() -> None:
    from cypher_dsl import create, lit, returning, union
    from cypher_dsl.clauses.call import SubqueryCallClause
    from cypher_dsl.statements.rules.call import CallRule, output_scope

    first = returning(name("p").alias("result")).build()
    second = returning(lit(1).alias("result")).build()
    clause = SubqueryCallClause(union(first, second), (name("p"),))
    frame = ScopeFrame((), unresolved=frozenset({"outer"}))
    after = CallRule().bindings(frame, clause)
    assert after.names == ("result",)
    assert after.unresolved == frozenset({"outer", "result"})
    seed = CallRule().enter_body(frame, clause)
    assert output_scope(create(node("Clone")).build(), seed).unresolved == frozenset()

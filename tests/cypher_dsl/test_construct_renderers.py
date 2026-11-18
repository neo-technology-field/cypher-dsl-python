from __future__ import annotations

import sys

import pytest

from cypher_dsl import (
    Clause,
    Condition,
    Expression,
    FunctionInvocation,
    NodePattern,
    PatternElement,
    assign,
    asterisk,
    call,
    call_procedure,
    condition,
    count,
    create,
    desc,
    element_id,
    fn,
    has_label,
    is_labeled,
    list_,
    lit,
    map_,
    match,
    merge,
    name,
    node,
    param,
    path_pattern,
    raw,
    returning,
    set_labels,
    union,
    unwind,
    update_properties,
)
from cypher_dsl.ast import AstNode, OccurrenceFacts, OccurrencePath
from cypher_dsl.clauses.projection import ProjectionClause
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.subqueries import CollectExpression, CountExpression, ExistsExpression, SubqueryExpression
from cypher_dsl.patterns.labels import ANY_LABEL, LabelExpression, label
from cypher_dsl.render.expressions import expression_bindings
from cypher_dsl.render.filters import filter_bindings
from cypher_dsl.render.patterns import pattern_bindings
from cypher_dsl.render.projections import projection_bindings
from cypher_dsl.render.rules import RenderingRules
from cypher_dsl.render.statements import shared_bindings, statement_bindings
from cypher_dsl.render.unwind import unwind_bindings
from cypher_dsl.render.updates import update_bindings
from cypher_dsl.statements.analysis import Analysis, NodePatternFacts, NoFacts
from cypher_dsl.statements.frames import DeclarationRole


def render(root: AstNode, rules: RenderingRules, facts: dict[OccurrencePath, OccurrenceFacts] | None = None) -> str:
    from cypher_dsl.render.traversal import RenderingTraversal

    paths: dict[OccurrencePath, OccurrenceFacts] = {}

    def walk(current: AstNode, path: OccurrencePath) -> None:
        paths[path] = NoFacts()
        for index, child in enumerate(current.children()):
            walk(child, (*path, index))

    walk(root, ())
    if facts:
        paths.update(facts)
    analysis = Analysis(paths, (), ())
    return RenderingTraversal(rules, analysis, always_escape_names=False).render(root)


def expression_rules() -> RenderingRules:
    return RenderingRules.from_bindings(expression_bindings())


def all_rules() -> RenderingRules:
    return RenderingRules.from_bindings((*expression_bindings(), *pattern_bindings()))


def statement_rules() -> RenderingRules:
    return RenderingRules.from_bindings(
        (
            *expression_bindings(),
            *pattern_bindings(),
            *filter_bindings(),
            *projection_bindings(),
            *unwind_bindings(),
            *update_bindings(),
            *statement_bindings(),
        )
    )


def declaration_facts(root: AstNode) -> dict[OccurrencePath, OccurrenceFacts]:
    facts: dict[OccurrencePath, OccurrenceFacts] = {}

    def walk(current: AstNode, path: OccurrencePath) -> None:
        if isinstance(current, NodePattern):
            facts[path] = NodePatternFacts(DeclarationRole.DECLARE)
        for index, child in enumerate(current.children()):
            walk(child, (*path, index))

    walk(root, ())
    return facts


def test_expression_bindings_render_grouping_and_parameters() -> None:
    rules = RenderingRules.from_bindings(expression_bindings())
    assert render(name("n")["title"] == lit("The Matrix"), rules) == "n.title = 'The Matrix'"
    assert render(-(lit(1) + lit(2)), rules) == "-(1 + 2)"
    assert render(param("data"), rules) == "$data"


def test_element_id_uses_the_shared_expression_rendering() -> None:
    rules = RenderingRules.from_bindings(expression_bindings())
    assert render(element_id(name("n")), rules) == "elementId(n)"


def test_node_pattern_requires_declaration_facts() -> None:
    rules = RenderingRules.from_bindings((*expression_bindings(), *pattern_bindings()))
    person = node("Person", name="p")
    with pytest.raises(DslError, match="NodePatternFacts"):
        render(person, rules)
    declare = render(person, rules, {(): NodePatternFacts(DeclarationRole.DECLARE)})
    reference = render(person, rules, {(): NodePatternFacts(DeclarationRole.REFERENCE)})
    assert declare == "(p:Person)"
    assert reference == "(p)"


def test_unary_and_private_operator_subclasses_use_their_public_rules() -> None:
    rules = expression_rules()
    assert render(+(lit(1) + lit(2)), rules) == "+(1 + 2)"
    assert render(+(-name("x")), rules) == "+(-x)"
    assert render(~(name("a") > 1), rules) == "NOT a > 1"
    assert render((name("a") > 1) & (name("b") < 2), rules) == "a > 1 AND b < 2"


def test_condition_operand_and_postfix_comparison_add_no_extra_syntax() -> None:
    rules = expression_rules()
    assert render(condition(name("flag")), rules) == "flag"
    assert render(name("x") == None, rules) == "x IS NULL"  # noqa: E711


def test_properties_subscripts_and_collections_render_child_expressions() -> None:
    rules = expression_rules()
    row = name("row")
    assert render(row[param("key")], rules) == "`row`[$key]"
    assert render(list_(row["uid"], 2), rules) == "[`row`.uid, 2]"
    assert render(map_({"uid": row["uid"], "since": param("since")}), rules) == "{uid: `row`.uid, since: $since}"


def test_functions_render_distinct_qualified_names_asterisks_and_raw_text() -> None:
    rules = expression_rules()
    assert render(count(name("n"), distinct=True), rules) == "count(DISTINCT n)"
    assert render(fn("point.distance", name("a"), name("b")), rules) == "point.distance(a, b)"
    assert render(FunctionInvocation(("point", "distance"), (name("a"),), True), rules) == (
        "point.distance(DISTINCT a)"
    )
    assert render(asterisk(), rules) == "*"
    assert render(raw("a + b"), rules) == "a + b"


def test_aliases_and_sort_items_render_their_suffixes() -> None:
    rules = expression_rules()
    assert render(fn("size", name("items")).alias("total"), rules) == "size(items) AS total"
    assert render(desc(name("released")), rules) == "released DESC"


def test_pattern_property_maps_share_expression_rendering() -> None:
    movie = node("Movie", name="m", properties={"title": "The Matrix", "released": 1999})
    assert render(movie, all_rules(), declaration_facts(movie)) == "(m:Movie {title: 'The Matrix', released: 1999})"
    named = node("Person", name="p", properties={"name": "Ada"})
    assert render(named, all_rules(), declaration_facts(named)) == "(p:Person {`name`: 'Ada'})"


def test_relationship_properties_and_directions_match_the_visitor() -> None:
    person = node("Person", name="p")
    colleague = node("Person", name="c")
    knows = person.relationship_to(colleague, "KNOWS", name="r", properties={"since": 1999})
    incoming = person.relationship_from(colleague, "KNOWS")
    undirected = person.relationship_with(colleague, "KNOWS")
    assert render(knows, all_rules(), declaration_facts(knows)) == ("(p:Person)-[r:KNOWS {since: 1999}]->(c:Person)")
    assert render(incoming, all_rules(), declaration_facts(incoming)) == "(p:Person)<-[:KNOWS]-(c:Person)"
    assert render(undirected, all_rules(), declaration_facts(undirected)) == "(p:Person)-[:KNOWS]-(c:Person)"


def test_match_with_where_and_projection_render_through_rules() -> None:
    person = node("Person", name="p")
    query = match(person).where(person["name"] == param("name", "Keanu")).returning(person["title"])
    root = query.build()
    assert render(root, statement_rules(), declaration_facts(root)) == (
        "MATCH (p:Person) WHERE p.`name` = $name RETURN p.title"
    )


def test_with_modifiers_render_before_the_filter_through_rules() -> None:
    movie = node("Movie", name="m")
    root = (
        match(movie)
        .with_(movie)
        .order_by(desc(movie["released"]))
        .skip(5)
        .limit(10)
        .where(movie["released"] > 2000)
        .returning(movie)
        .build()
    )
    assert render(root, statement_rules(), declaration_facts(root)) == (
        "MATCH (m:Movie) WITH m ORDER BY m.released DESC SKIP 5 LIMIT 10 WHERE m.released > 2000 RETURN m"
    )


def test_unwind_quotes_its_alias_through_rules() -> None:
    root = unwind(param("rows"), name("row")).returning(name("row")).build()
    assert render(root, statement_rules()) == "UNWIND $rows AS `row` RETURN `row`"


def test_merge_actions_render_in_call_order_through_rules() -> None:
    person = node("Person", name="p", properties={"uid": param("uid", "p1")})
    root = (
        merge(person)
        .on_create(assign(person["created"], param("created", "2026-11-13")))
        .on_match(assign(person["seen"], param("seen", "2026-11-13")))
        .returning(person["uid"])
        .build()
    )
    assert render(root, statement_rules(), declaration_facts(root)) == (
        "MERGE (p:Person {uid: $uid}) ON CREATE SET p.created = $created ON MATCH SET p.seen = $seen RETURN p.uid"
    )


def test_set_renders_property_and_label_updates_through_rules() -> None:
    person = node("Person", name="p")
    root = match(person).set_(assign(person["given"], "Ada"), set_labels(person, "Employee")).build()
    assert render(root, statement_rules(), declaration_facts(root)) == (
        "MATCH (p:Person) SET p.given = 'Ada', p:Employee"
    )


def test_patch_and_dynamic_writes_render_without_target_policy_through_rules() -> None:
    person = node("Person", name="p")
    patched = match(person).set_(update_properties(person, param("properties", {"given": "Ada"}))).build()
    dynamic = match(person).set_(assign(person[param("key", "given")], "Ada")).build()
    assert render(patched, statement_rules(), declaration_facts(patched)) == ("MATCH (p:Person) SET p += $properties")
    assert render(dynamic, statement_rules(), declaration_facts(dynamic)) == "MATCH (p:Person) SET p[$key] = 'Ada'"


def test_remove_renders_properties_and_labels_through_rules() -> None:
    person = node("Person", name="p")
    property_root = match(person).remove(person["nickname"]).build()
    label_root = match(person).remove(set_labels(person, "Employee")).build()
    assert render(property_root, statement_rules(), declaration_facts(property_root)) == (
        "MATCH (p:Person) REMOVE p.nickname"
    )
    assert render(label_root, statement_rules(), declaration_facts(label_root)) == "MATCH (p:Person) REMOVE p:Employee"


def test_delete_renders_plain_and_detached_forms_through_rules() -> None:
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    plain = match(person, movie).delete(person, movie).build()
    detached = match(person).detach_delete(person).build()
    assert render(plain, statement_rules(), declaration_facts(plain)) == ("MATCH (p:Person), (m:Movie) DELETE p, m")
    assert render(detached, statement_rules(), declaration_facts(detached)) == "MATCH (p:Person) DETACH DELETE p"


@pytest.mark.parametrize(
    ("all", "separator"),
    [(False, " UNION "), (True, " UNION ALL ")],
)
def test_union_variants_render_through_rules(all: bool, separator: str) -> None:
    root = union(returning(lit(1).alias("x")), returning(lit(2).alias("x")), all=all)
    assert render(root, statement_rules()) == f"RETURN 1 AS x{separator}RETURN 2 AS x"


def test_element_id_renders_through_rules() -> None:
    rules = RenderingRules.from_bindings(shared_bindings())
    assert render(element_id(name("n")), rules) == "elementId(n)"


def test_shared_bindings_render_every_concrete_grammar_node() -> None:
    # A family base is abstract, and the subquery-expression base cannot be constructed standalone,
    # so only concrete subclasses are renderable roots.
    abstract_bases = {
        Clause,
        Condition,
        Expression,
        LabelExpression,
        PatternElement,
        ProjectionClause,
        SubqueryExpression,
    }

    def subclasses(parent: type[AstNode]) -> set[type[AstNode]]:
        found: set[type[AstNode]] = set()
        for child in parent.__subclasses__():
            found.add(child)
            found.update(subclasses(child))
        return found

    # A slots-based dataclass leaves its superseded class in the base's subclass list.
    concrete = {
        candidate
        for candidate in subclasses(AstNode)
        if candidate.__module__.startswith("cypher_dsl.")
        and getattr(sys.modules[candidate.__module__], candidate.__qualname__, None) is candidate
        and candidate not in abstract_bases
    }
    person = node("Person", name="p", properties={"uid": param("uid")})
    other = node("Person", name="q")
    relationship = person.relationship_to(other, "KNOWS", name="r", properties={"since": 1999})
    roots: tuple[AstNode, ...] = (
        -(lit(1) + lit(2)),
        ~(name("a") > 1),
        condition(name("flag")),
        ExistsExpression(match(person).returning(person).build()),
        CountExpression(match(person).returning(person).build()),
        CollectExpression(match(person).returning(person["uid"]).build()),
        name("n")[param("key")],
        list_(name("n"), 2),
        map_({"uid": name("n")}),
        element_id(name("n")),
        fn("size", name("items")),
        has_label(person, label("A") | ~label("B")),
        is_labeled(person, label("A") | ~label("B")),
        asterisk(),
        raw("n"),
        match(relationship).where((person["uid"] > 0) & (other["uid"] < 2)).returning(person).build(),
        match(relationship).where(path_pattern(relationship)).returning(person).build(),
        match(person)
        .with_(person)
        .order_by(desc(person["uid"]))
        .skip(1)
        .limit(1)
        .where(person["uid"] > 0)
        .returning(person)
        .build(),
        unwind(param("rows"), name("row")).returning(name("row")).build(),
        call(returning(lit(1).alias("x"))).returning(name("x")).build(),
        call_procedure("db.labels", param("first"))
        .yielding(name("label"))
        .where(name("label") != lit("x"))
        .returning(name("label"))
        .build(),
        create(relationship).build(),
        merge(person).on_create(assign(person["created"], True)).on_match(assign(person["seen"], True)).build(),
        match(person)
        .set_(
            assign(person["given"], "Ada"),
            update_properties(person, param("properties")),
            set_labels(person, "Staff"),
        )
        .build(),
        match(person).remove(person["nickname"], set_labels(person, "Employee")).build(),
        match(person).delete(person).build(),
        match(person).detach_delete(person).build(),
        union(returning(lit(1).alias("x")), returning(lit(2).alias("x"))),
        union(returning(lit(1).alias("x")), returning(lit(2).alias("x")), all=True),
        match(
            node((label("A") & label("B")) | ~label("C"), name="p"),
            node(ANY_LABEL),
            node("Person").with_labels("Staff"),
        )
        .returning(lit(1))
        .build(),
    )
    rendered: set[type[AstNode]] = set()
    rules = RenderingRules.from_bindings(shared_bindings())
    for root in roots:
        render(root, rules, declaration_facts(root))

        def collect(current: AstNode) -> None:
            rendered.add(type(current))
            for child in current.children():
                collect(child)

        collect(root)
    assert not concrete - rendered, f"Grammar nodes without a shared-rule rendering: {concrete - rendered}"

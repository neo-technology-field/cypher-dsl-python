# Ported from the Java Cypher-DSL test suite (neo4j/cypher-dsl, Apache-2.0).
# Traced source: CypherIT. Rewritten for pytest.
"""
``WITH``, projection modifiers and pagination.

``WITH`` ends one query part and starts the next, so the tests pin which names survive it,
where its own filter belongs and how DISTINCT, ORDER BY, SKIP and LIMIT attach to the
projection that owns them. Pagination literals are checked where they enter the syntax,
while parameterised or computed pagination stays an expression whose runtime value the
library does not pretend to know.
"""

from __future__ import annotations

import pytest

from cypher_dsl import (
    Configuration,
    MatchClause,
    Renderer,
    ReturnClause,
    SortItem,
    Statement,
    StatementBuilder,
    SymbolicName,
    Variable,
    Where,
    WithClause,
    asc,
    asterisk,
    count,
    desc,
    lit,
    match,
    name,
    node,
    param,
    raw,
    with_,
)
from cypher_dsl.clauses.projection import ProjectionClause
from cypher_dsl.errors import DslError, InvalidClauseOrderError


def test_with_renders_a_projection_that_the_next_part_can_use():
    movie = node("Movie", name="m")
    query = match(movie).with_(movie).returning(movie)
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == "MATCH (m:Movie) WITH m RETURN m"


def test_with_filter_keeps_an_alias_in_scope():
    movie = node("Movie", name="m")
    query = match(movie).with_(movie["released"].alias("year")).where(name("year") > 2000).returning(name("year"))
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (m:Movie) WITH m.released AS year WHERE year > 2000 RETURN year"
    )


def test_with_distinct_belongs_to_the_with_projection():
    movie = node("Movie", name="m")
    query = match(movie).with_(movie["released"].alias("year")).distinct().returning(name("year"))
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (m:Movie) WITH DISTINCT m.released AS year RETURN year"
    )


def test_return_distinct_belongs_to_the_return_projection():
    movie = node("Movie", name="m")
    query = match(movie).returning(movie["released"].alias("year")).distinct()
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (m:Movie) RETURN DISTINCT m.released AS year"
    )


def test_distinct_only_modifies_the_current_projection():
    movie = node("Movie", name="m")
    query = match(movie).with_(movie).distinct().returning(movie)
    assert (
        Renderer.get(Configuration(server_version="5.26")).render(query).cypher
        == "MATCH (m:Movie) WITH DISTINCT m RETURN m"
    )


def test_order_by_appends_items_to_the_current_projection():
    movie = node("Movie", name="m")
    query = match(movie).returning(movie).order_by(movie["title"]).order_by(desc(movie["released"]))
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (m:Movie) RETURN m ORDER BY m.title, m.released DESC"
    )


def test_a_bare_order_item_does_not_gain_an_asc_token():
    movie = node("Movie", name="m")
    query = match(movie).returning(movie).order_by(movie["title"])
    assert (
        Renderer.get(Configuration(server_version="5.26")).render(query).cypher
        == "MATCH (m:Movie) RETURN m ORDER BY m.title"
    )


def test_explicit_ascending_order_keeps_the_token():
    movie = node("Movie", name="m")
    query = match(movie).returning(movie).order_by(asc(movie["title"]))
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (m:Movie) RETURN m ORDER BY m.title ASC"
    )


def test_with_modifiers_render_before_the_with_filter():
    movie = node("Movie", name="m")
    query = (
        match(movie)
        .with_(movie)
        .order_by(desc(movie["released"]))
        .skip(5)
        .limit(10)
        .where(movie["released"] > 2000)
        .returning(movie)
    )
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (m:Movie) WITH m ORDER BY m.released DESC SKIP 5 LIMIT 10 WHERE m.released > 2000 RETURN m"
    )


def test_projection_records_the_attached_modifiers():
    movie = node("Movie", name="m")
    query = match(movie).returning(movie).distinct().order_by(desc(movie["released"])).skip(1).limit(2)
    clause = query.clauses[-1]
    assert isinstance(clause, ReturnClause)
    assert clause.distinct is True
    assert len(clause.order_by) == 1
    assert isinstance(clause.order_by[0], SortItem)
    assert clause.skip is not None
    assert clause.limit is not None


def test_pagination_accepts_parameters_and_expressions():
    movie = node("Movie", name="m")
    query = match(movie).returning(movie).skip(param("offset", 10)).limit(name("page_size") + 1)
    rendered = Renderer.get(Configuration(server_version="5.26")).render(query)
    assert rendered.cypher == "MATCH (m:Movie) RETURN m SKIP $offset LIMIT page_size + 1"
    assert rendered.parameters == {"offset": 10}


@pytest.mark.parametrize("value", [-1, True, False, 1.5, "5"])
def test_literal_pagination_must_be_a_non_negative_integer(value):
    movie = node("Movie", name="m")
    with pytest.raises(DslError, match="non-negative integer"):
        match(movie).returning(movie).limit(value)
    with pytest.raises(DslError, match="non-negative integer"):
        match(movie).returning(movie).skip(value)


def test_parameterised_pagination_is_not_guessed():
    movie = node("Movie", name="m")
    rendered = Renderer.get(Configuration(server_version="5.26")).render(
        match(movie).returning(movie).limit(param("size"))
    )
    assert rendered.cypher == "MATCH (m:Movie) RETURN m LIMIT $size"
    assert rendered.unbound_parameters == frozenset({"size"})


def test_duplicate_skip_is_rejected():
    movie = node("Movie", name="m")
    with pytest.raises(DslError, match="SKIP"):
        match(movie).returning(movie).skip(1).skip(2)


def test_duplicate_limit_is_rejected():
    movie = node("Movie", name="m")
    with pytest.raises(DslError, match="LIMIT"):
        match(movie).returning(movie).limit(1).limit(2)


def test_empty_with_projection_is_rejected():
    with pytest.raises(DslError, match="WITH"):
        with_()
    with pytest.raises(DslError, match="WITH"):
        match(node("Movie", name="m")).with_()


def test_empty_order_by_is_rejected():
    movie = node("Movie", name="m")
    with pytest.raises(DslError, match="ORDER BY"):
        match(movie).returning(movie).order_by()


@pytest.mark.parametrize("modifier", ["distinct", "order_by", "skip", "limit"])
def test_projection_modifiers_need_a_projection_owner(modifier):
    movie = node("Movie", name="m")
    query = match(movie)
    arguments = {"order_by": (movie,), "skip": (1,), "limit": (1,)}.get(modifier, ())
    with pytest.raises(DslError, match="projection"):
        getattr(query, modifier)(*arguments)


def test_projection_modifiers_need_a_clause_at_all():
    with pytest.raises(DslError, match="projection"):
        StatementBuilder().limit(1)


def test_with_and_return_cannot_follow_return():
    movie = node("Movie", name="m")
    query = match(movie).returning(movie)
    with pytest.raises(InvalidClauseOrderError):
        query.with_(movie)
    with pytest.raises(InvalidClauseOrderError):
        query.returning(movie)


def test_alias_is_quoted_in_a_with_projection():
    movie = node("Movie", name="m")
    query = match(movie).with_(movie["released"].alias("year of release")).returning(name("year of release"))
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (m:Movie) WITH m.released AS `year of release` RETURN `year of release`"
    )


def test_a_reserved_alias_is_quoted_in_a_projection():
    movie = node("Movie", name="m")
    query = match(movie).returning(movie["title"].alias("match"))
    assert (
        Renderer.get(Configuration(server_version="5.26")).render(query).cypher
        == "MATCH (m:Movie) RETURN m.title AS `match`"
    )


def test_a_discarded_variable_is_rejected_after_with():
    movie = node("Movie", name="m")
    query = match(movie).with_(movie["released"].alias("year"))
    with pytest.raises(DslError, match="not in scope"):
        query.returning(movie["title"])


def test_an_ordinary_with_filter_can_still_use_its_input_variable():
    movie = node("Movie", name="m")
    query = match(movie).with_(movie["released"].alias("year"))
    filtered = query.where(movie["released"] > 2000).returning(name("year"))
    assert Renderer.get(Configuration(server_version="5.26")).render(filtered).cypher == (
        "MATCH (m:Movie) WITH m.released AS year WHERE m.released > 2000 RETURN year"
    )


@pytest.mark.parametrize("direct", [False, True])
def test_with_filter_reads_input_and_output_after_a_previous_scope_boundary(direct):
    person = node("Person", name="p")
    predicate = (person["active"] == lit(True)) & (name("uid") > 0)
    if direct:
        query = Statement(
            (
                MatchClause((person,)),
                WithClause((person.as_expression(),)),
                WithClause((person["uid"].alias("uid"),), where=Where(predicate)),
                ReturnClause((name("uid"),)),
            )
        )
    else:
        query = match(person).with_(person).with_(person["uid"].alias("uid")).where(predicate).returning(name("uid"))
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (p:Person) WITH p WITH p.uid AS uid WHERE p.`active` = true AND uid > 0 RETURN uid"
    )


def test_with_filter_cannot_restore_a_name_discarded_by_an_earlier_with():
    person, movie = node("Person", name="p"), node("Movie", name="m")
    with pytest.raises(DslError, match="not in scope"):
        match(person, movie).with_(person).with_(person["uid"].alias("uid")).where(movie["released"] > 2000)


@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize("aggregate", [False, True])
def test_distinct_and_aggregating_with_filters_cannot_read_discarded_inputs(direct, aggregate):
    person = node("Person", name="p")
    expression = count(person).alias("total") if aggregate else person["uid"].alias("uid")
    with pytest.raises(DslError, match="not in scope"):
        if direct:
            Statement(
                (
                    MatchClause((person,)),
                    WithClause((expression,), distinct=not aggregate, where=Where(person["active"] == lit(True))),
                    ReturnClause((lit(1),)),
                )
            )
        else:
            query = match(person).with_(expression)
            if not aggregate:
                query = query.distinct()
            query.where(person["active"] == lit(True))


def test_adding_distinct_revalidates_an_existing_with_filter():
    person = node("Person", name="p")
    query = match(person).with_(person["uid"].alias("uid")).where(person["active"] == lit(True))
    with pytest.raises(DslError, match="not in scope"):
        query.distinct()


@pytest.mark.parametrize("aggregate", [False, True])
def test_restricting_with_filter_can_use_its_projected_alias(aggregate):
    person = node("Person", name="p")
    expression = count(person).alias("value") if aggregate else person["uid"].alias("value")
    query = match(person).with_(expression)
    if not aggregate:
        query = query.distinct()
    result = query.where(name("value") > 0).returning(name("value"))
    expected = "count(p)" if aggregate else "DISTINCT p.uid"
    assert Renderer.get(Configuration(server_version="5.26")).render(result).cypher == (
        f"MATCH (p:Person) WITH {expected} AS `value` WHERE `value` > 0 RETURN `value`"
    )


def test_a_discarded_variable_is_rejected_in_a_projection_modifier():
    movie = node("Movie", name="m")
    query = match(movie).with_(movie["released"].alias("year")).returning(name("year"))
    with pytest.raises(DslError, match="not in scope"):
        query.order_by(movie["title"])


def test_a_projected_name_remains_available():
    movie = node("Movie", name="m")
    query = match(movie).with_(movie).returning(movie["title"])
    assert (
        Renderer.get(Configuration(server_version="5.26")).render(query).cypher
        == "MATCH (m:Movie) WITH m RETURN m.title"
    )


def test_a_raw_projection_does_not_certify_scope():
    movie = node("Movie", name="m")
    query = match(movie).with_(raw("m")).returning(movie["title"])
    assert (
        Renderer.get(Configuration(server_version="5.26")).render(query).cypher
        == "MATCH (m:Movie) WITH m RETURN m.title"
    )


def test_an_ordinary_projection_keeps_the_known_input_scope_for_ordering():
    movie = node("Movie", name="m")
    person = node("Person", name="p")
    query = match(movie, person).with_(person).returning(person["given"])
    with pytest.raises(DslError, match="not in scope"):
        query.order_by(movie["title"])


def test_an_ordinary_projection_keeps_the_known_input_scope_for_pagination():
    movie = node("Movie", name="m")
    person = node("Person", name="p")
    query = match(movie, person).with_(person).returning(person["given"])
    with pytest.raises(DslError, match="not in scope"):
        query.limit(movie["released"])


def test_an_ordinary_projection_can_order_by_a_retained_input_name():
    movie = node("Movie", name="m")
    person = node("Person", name="p")
    query = match(movie, person).with_(person).returning(person["given"]).order_by(person["email"])
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (m:Movie), (p:Person) WITH p RETURN p.given ORDER BY p.email"
    )


def test_distinct_restricts_ordering_to_projected_names():
    movie = node("Movie", name="m")
    person = node("Person", name="p")
    query = match(movie, person).with_(person).returning(person["given"]).distinct()
    with pytest.raises(DslError, match="not in scope"):
        query.order_by(movie["title"])


def test_distinct_restricts_ordering_after_two_known_projections():
    query = with_(lit(1).alias("one")).with_(lit(2).alias("two")).distinct()
    with pytest.raises(DslError, match="not in scope"):
        query.order_by(name("one"))


def test_the_first_with_distinct_restricts_ordering_as_well():
    movie = node("Movie", name="m")
    query = match(movie).with_(movie["released"].alias("year")).distinct()
    with pytest.raises(DslError, match="not in scope"):
        query.order_by(movie["title"])


def test_a_known_aggregate_restricts_ordering_to_projected_names():
    movie = node("Movie", name="m")
    query = match(movie).with_(count(movie).alias("total"))
    with pytest.raises(DslError, match="not in scope"):
        query.order_by(movie["title"])


def test_distinct_added_after_ordering_revalidates_the_existing_modifier():
    movie = node("Movie", name="m")
    query = match(movie).with_(movie["released"].alias("year")).order_by(movie["title"])
    with pytest.raises(DslError, match="not in scope"):
        query.distinct()


def test_distinct_restricts_pagination_to_projected_names():
    movie = node("Movie", name="m")
    query = match(movie).with_(movie["released"].alias("year")).distinct()
    with pytest.raises(DslError, match="not in scope"):
        query.skip(movie["released"])


def test_distinct_ordering_may_derive_from_a_projected_property():
    movie = node("Movie", name="m")
    query = match(movie).returning(movie["released"]).distinct().order_by(movie["released"] + 1)
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (m:Movie) RETURN DISTINCT m.released ORDER BY m.released + 1"
    )


def test_aggregate_ordering_may_derive_from_a_projected_aggregate():
    movie = node("Movie", name="m")
    query = match(movie).returning(count(movie)).order_by(count(movie) + 1)
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (m:Movie) RETURN count(m) ORDER BY count(m) + 1"
    )


def test_distinct_ordering_may_not_reach_outside_a_projected_subtree():
    movie = node("Movie", name="m")
    query = match(movie).returning(movie["released"]).distinct()
    with pytest.raises(DslError, match="not in scope"):
        query.order_by(movie["released"] + movie["title"])


def test_aggregate_ordering_may_not_reach_outside_a_projected_subtree():
    movie = node("Movie", name="m")
    query = match(movie).returning(count(movie))
    with pytest.raises(DslError, match="not in scope"):
        query.order_by(count(movie) + movie["title"])


def test_distinct_ordering_by_the_projected_expression_is_allowed():
    movie = node("Movie", name="m")
    query = match(movie).returning(movie["released"]).distinct().order_by(movie["released"])
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (m:Movie) RETURN DISTINCT m.released ORDER BY m.released"
    )


def test_distinct_ordering_by_a_projected_name_is_allowed():
    movie = node("Movie", name="m")
    query = (
        match(movie).with_(movie["released"].alias("year")).distinct().order_by(name("year")).returning(name("year"))
    )
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (m:Movie) WITH DISTINCT m.released AS year ORDER BY year RETURN year"
    )


def test_with_wildcard_keeps_the_known_scope():
    movie = node("Movie", name="m")
    person = node("Person", name="p")
    query = match(movie, person).with_(person).with_(asterisk()).returning(person)
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (m:Movie), (p:Person) WITH p WITH * RETURN p"
    )


def test_with_wildcard_cannot_restore_a_discarded_name():
    movie = node("Movie", name="m")
    person = node("Person", name="p")
    query = match(movie, person).with_(person).with_(asterisk())
    with pytest.raises(DslError, match="not in scope"):
        query.returning(movie)


def test_with_requires_an_alias_for_a_non_variable_item():
    movie = node("Movie", name="m")
    with pytest.raises(DslError, match="alias"):
        match(movie).with_(lit(1))
    with pytest.raises(DslError, match="alias"):
        match(movie).with_(movie["title"])
    with pytest.raises(DslError, match="alias"):
        match(movie).with_(count(movie))


def test_return_does_not_require_an_alias_for_a_non_variable_item():
    movie = node("Movie", name="m")
    query = match(movie).returning(lit(1), movie["title"], count(movie))
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (m:Movie) RETURN 1, m.title, count(m)"
    )


def test_the_shared_projection_body_cannot_be_instantiated():
    with pytest.raises(DslError, match="WithClause or ReturnClause"):
        ProjectionClause((lit(1),))


def test_projection_items_must_be_a_tuple():
    items = [name("m")]
    with pytest.raises(DslError, match="tuple"):
        WithClause(items)  # type: ignore[arg-type]


def test_projection_order_items_must_be_a_tuple():
    with pytest.raises(DslError, match="tuple"):
        WithClause((name("m"),), order_by=[name("m")])  # type: ignore[arg-type]


def test_an_aliased_aggregate_discards_its_source_variable():
    movie = node("Movie", name="m")
    query = match(movie).with_(count(movie).alias("total"))
    with pytest.raises(DslError, match="not in scope"):
        query.returning(movie["title"])


def test_repeated_rendering_does_not_change_projection_metadata():
    movie = node("Movie", name="m")
    query = match(movie).returning(movie).distinct().order_by(desc(movie["released"])).skip(1).limit(2)
    clause = query.clauses[-1]
    before = (clause.distinct, clause.order_by, clause.skip, clause.limit)
    renderer = Renderer.get(Configuration(server_version="5.26"))
    assert renderer.render(query).cypher == renderer.render(query).cypher
    assert (clause.distinct, clause.order_by, clause.skip, clause.limit) == before


def test_directly_constructed_with_clause_validates_its_pagination():
    with pytest.raises(DslError, match="non-negative integer"):
        WithClause((Variable(SymbolicName("m")),), skip=lit(-1))


def test_directly_constructed_with_clause_rejects_an_empty_projection():
    with pytest.raises(DslError, match="WITH"):
        WithClause(())


def test_directly_constructed_projection_rejects_a_non_expression_item():
    with pytest.raises(DslError, match="expression"):
        WithClause(("m",))  # type: ignore[arg-type]


def _render_forced_escaping(query):
    """
    Render with the Python equivalent of the pinned Java default configuration.

    The pinned Java default forces escaping of labels and relationship types. This
    renderer applies the same setting to variables, property keys, aliases and parameter
    names as well, so the ported text below carries extra backticks. Each fixture records
    the pinned Java expectation in a comment, and the divergence is deliberate.
    """
    return Renderer.get(Configuration(server_version="5.26", always_escape_names=True)).render(query)


def test_upstream_default_sort_order():
    # Pinned: MATCH (u:`User`) RETURN u ORDER BY u.name
    user = node("User", name="u")
    assert _render_forced_escaping(match(user).returning(user).order_by(user["name"])).cypher == (
        "MATCH (`u`:`User`) RETURN `u` ORDER BY `u`.`name`"
    )


def test_upstream_ascending_sort_order():
    # Pinned: MATCH (u:`User`) RETURN u ORDER BY u.name ASC
    user = node("User", name="u")
    assert _render_forced_escaping(match(user).returning(user).order_by(asc(user["name"]))).cypher == (
        "MATCH (`u`:`User`) RETURN `u` ORDER BY `u`.`name` ASC"
    )


def test_upstream_descending_sort_order():
    # Pinned: MATCH (u:`User`) RETURN u ORDER BY u.name DESC
    user = node("User", name="u")
    assert _render_forced_escaping(match(user).returning(user).order_by(desc(user["name"]))).cypher == (
        "MATCH (`u`:`User`) RETURN `u` ORDER BY `u`.`name` DESC"
    )


def test_upstream_concatenated_sort_order():
    # Pinned: MATCH (u:`User`) RETURN u ORDER BY u.name DESC, u.age ASC
    user = node("User", name="u")
    query = match(user).returning(user).order_by(desc(user["name"]), asc(user["age"]))
    assert _render_forced_escaping(query).cypher == (
        "MATCH (`u`:`User`) RETURN `u` ORDER BY `u`.`name` DESC, `u`.`age` ASC"
    )


def test_upstream_skip():
    # Pinned: MATCH (u:`User`) RETURN u SKIP 1
    user = node("User", name="u")
    assert _render_forced_escaping(match(user).returning(user).skip(1)).cypher == (
        "MATCH (`u`:`User`) RETURN `u` SKIP 1"
    )


def test_upstream_limit():
    # Pinned: MATCH (u:`User`) RETURN u LIMIT 1
    user = node("User", name="u")
    assert _render_forced_escaping(match(user).returning(user).limit(1)).cypher == (
        "MATCH (`u`:`User`) RETURN `u` LIMIT 1"
    )


def test_upstream_skip_and_limit():
    # Pinned: MATCH (u:`User`) RETURN u SKIP 1 LIMIT 1
    user = node("User", name="u")
    assert _render_forced_escaping(match(user).returning(user).skip(1).limit(1)).cypher == (
        "MATCH (`u`:`User`) RETURN `u` SKIP 1 LIMIT 1"
    )


def test_upstream_limit_with_parameter():
    # Pinned: MATCH (u:`User`) RETURN u LIMIT $param
    user = node("User", name="u")
    rendered = _render_forced_escaping(match(user).returning(user).limit(param("param")))
    assert rendered.cypher == "MATCH (`u`:`User`) RETURN `u` LIMIT $`param`"
    assert rendered.unbound_parameters == frozenset({"param"})


def test_upstream_skip_and_limit_with_parameters():
    # Pinned: MATCH (u:`User`) RETURN u SKIP $skip LIMIT $limit
    user = node("User", name="u")
    rendered = _render_forced_escaping(match(user).returning(user).skip(param("skip")).limit(param("limit")))
    assert rendered.cypher == "MATCH (`u`:`User`) RETURN `u` SKIP $`skip` LIMIT $`limit`"
    assert rendered.unbound_parameters == frozenset({"skip", "limit"})


def test_upstream_distinct_with_pagination():
    # Pinned: MATCH (u:`User`) RETURN DISTINCT u SKIP 1 LIMIT 1
    user = node("User", name="u")
    assert _render_forced_escaping(match(user).returning(user).distinct().skip(1).limit(1)).cypher == (
        "MATCH (`u`:`User`) RETURN DISTINCT `u` SKIP 1 LIMIT 1"
    )

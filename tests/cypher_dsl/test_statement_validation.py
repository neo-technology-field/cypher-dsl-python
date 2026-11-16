"""
Statement finalisation, clause transitions and union compatibility.

A read statement is finalisable only when it ends in ``RETURN``. Clause transitions are
grammar state, so a query cannot accept a clause the previous clause forbids, and a
directly constructed statement applies the same rules as the fluent builder. Union parts
are validated independently; no scope state is shared between branches.
"""

from __future__ import annotations

import pytest

from cypher_dsl import (
    Configuration,
    MatchClause,
    Renderer,
    ReturnClause,
    Statement,
    StatementBuilder,
    SymbolicName,
    Variable,
    WithClause,
    asterisk,
    lit,
    match,
    name,
    node,
    returning,
    union,
    with_,
)
from cypher_dsl.errors import DslError, InvalidClauseOrderError


def test_branching_does_not_mutate_a_shared_prefix():
    movie = node("Movie", name="m")
    base = match(movie)
    titles = base.returning(movie["title"]).limit(5)
    years = base.returning(movie["released"]).order_by(movie["released"])
    renderer = Renderer.get(Configuration(server_version="5.26"))
    assert renderer.render(titles).cypher == "MATCH (m:Movie) RETURN m.title LIMIT 5"
    assert renderer.render(years).cypher == "MATCH (m:Movie) RETURN m.released ORDER BY m.released"


def test_where_cannot_follow_return():
    movie = node("Movie", name="m")
    with pytest.raises(InvalidClauseOrderError):
        match(movie).returning(movie).where(movie["released"] > 2000)


def test_match_and_optional_match_cannot_follow_return():
    movie = node("Movie", name="m")
    query = match(movie).returning(movie)
    with pytest.raises(InvalidClauseOrderError):
        query.match(movie)
    with pytest.raises(InvalidClauseOrderError):
        query.optional_match(movie)


def test_a_match_only_statement_cannot_be_finalised():
    with pytest.raises(DslError, match="RETURN"):
        match(node("Movie", name="m")).build()


def test_a_with_only_statement_cannot_be_finalised():
    movie = node("Movie", name="m")
    with pytest.raises(DslError, match="RETURN"):
        match(movie).with_(movie).build()


def test_with_then_return_is_finalisable():
    movie = node("Movie", name="m")
    statement = match(movie).with_(movie).returning(movie).build()
    assert (
        Renderer.get(Configuration(server_version="5.26")).render(statement).cypher == "MATCH (m:Movie) WITH m RETURN m"
    )


def test_a_directly_constructed_statement_accepts_a_complete_read():
    movie = node("Movie", name="m")
    statement = Statement(match(movie).with_(movie).returning(movie).clauses)
    assert (
        Renderer.get(Configuration(server_version="5.26")).render(statement).cypher == "MATCH (m:Movie) WITH m RETURN m"
    )


def test_a_directly_constructed_statement_rejects_a_with_terminal_clause():
    movie = node("Movie", name="m")
    with pytest.raises(DslError, match="RETURN"):
        Statement((*match(movie).clauses, WithClause((movie.as_expression(),))))


def test_a_directly_constructed_statement_rejects_a_discarded_reference():
    with_clause = WithClause((lit(1).alias("one"),))
    return_clause = ReturnClause((Variable(SymbolicName("m")),))
    with pytest.raises(DslError, match="not in scope"):
        Statement((with_clause, return_clause))


def test_a_directly_constructed_statement_validates_projection_pagination():
    with pytest.raises(DslError, match="non-negative integer"):
        ReturnClause((lit(1),), limit=lit(-1))


def test_a_directly_constructed_statement_checks_modifier_scope():
    movie = node("Movie", name="m")
    person = node("Person", name="p")
    with_clause = WithClause((person.as_expression(),))
    ordered = ReturnClause((person["given"],), order_by=(movie["title"],))
    limited = ReturnClause((person["given"],), limit=movie["title"])
    with pytest.raises(DslError, match="not in scope"):
        Statement((with_clause, ordered))
    with pytest.raises(DslError, match="not in scope"):
        Statement((with_clause, limited))


def test_a_directly_constructed_statement_checks_distinct_ordering():
    movie = node("Movie", name="m")
    with_clause = WithClause(
        (movie["released"].alias("year"),),
        distinct=True,
        order_by=(movie["title"],),
    )
    with pytest.raises(DslError, match="not in scope"):
        Statement((with_clause, ReturnClause((name("year"),))))


def test_a_directly_constructed_statement_allows_derived_ordering():
    movie = node("Movie", name="m")
    with_clause = WithClause(
        (movie["released"].alias("year"),),
        distinct=True,
        order_by=(movie["released"] + 1,),
    )
    statement = Statement((with_clause, ReturnClause((name("year"),))))
    assert Renderer.get(Configuration(server_version="5.26")).render(statement).cypher == (
        "WITH DISTINCT m.released AS year ORDER BY m.released + 1 RETURN year"
    )


def test_a_directly_constructed_statement_rejects_ordering_outside_a_projection():
    movie = node("Movie", name="m")
    with_clause = WithClause(
        (movie["released"].alias("year"),),
        distinct=True,
        order_by=(movie["released"] + movie["title"],),
    )
    with pytest.raises(DslError, match="not in scope"):
        Statement((with_clause, ReturnClause((name("year"),))))


def test_union_rejects_incompatible_singleton_wildcard_names():
    with pytest.raises(DslError, match="UNION projection"):
        union(
            with_(lit(1).alias("a")).returning(asterisk()),
            returning(lit(2).alias("b")),
        )


def test_union_accepts_compatible_singleton_wildcard_names():
    query = union(
        with_(lit(1).alias("a")).returning(asterisk()),
        returning(lit(2).alias("a")),
    )
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "WITH 1 AS a RETURN * UNION RETURN 2 AS a"
    )


def test_union_keeps_multicolumn_wildcard_positions_uncertain():
    left = with_(lit(1).alias("a"), lit(2).alias("b")).returning(asterisk())
    right = returning(lit(3).alias("c"), lit(4).alias("d"))
    assert Renderer.get(Configuration(server_version="5.26")).render(union(left, right)).cypher == (
        "WITH 1 AS a, 2 AS b RETURN * UNION RETURN 3 AS c, 4 AS d"
    )


def test_a_directly_constructed_statement_checks_later_match_properties():
    movie = node("Movie", name="m")
    person = node("Person", name="p")
    with_clause = WithClause((person.as_expression(),))
    later_match = MatchClause((node("Person", name="q", properties={"source": movie["title"]}),))
    with pytest.raises(DslError, match="not in scope"):
        Statement((with_clause, later_match, ReturnClause((name("q"),))))


def test_union_expands_a_known_wildcard_width():
    left = with_(lit(1).alias("a"), lit(2).alias("b")).returning(asterisk())
    right = returning(lit(3).alias("a"), lit(4).alias("b"))
    assert Renderer.get(Configuration(server_version="5.26")).render(union(left, right)).cypher == (
        "WITH 1 AS a, 2 AS b RETURN * UNION RETURN 3 AS a, 4 AS b"
    )


def test_union_does_not_certify_an_unknown_wildcard_width():
    query = union(returning(asterisk()), returning(name("a"), name("b")))
    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == "RETURN * UNION RETURN a, b"


def test_union_composes_projection_modifiers_per_branch():
    movie = node("Movie", name="m")
    first = match(movie).returning(movie["title"].alias("title")).limit(1)
    second = match(movie).returning(movie["released"].alias("title")).skip(1)
    assert Renderer.get(Configuration(server_version="5.26")).render(union(first, second)).cypher == (
        "MATCH (m:Movie) RETURN m.title AS title LIMIT 1 UNION MATCH (m:Movie) RETURN m.released AS title SKIP 1"
    )


def test_union_rejects_different_projection_widths_after_modifiers():
    with pytest.raises(DslError, match="UNION branches"):
        union(returning(lit(1)).distinct(), returning(name("x"), name("y")))


def test_union_rejects_incompatible_projection_names_after_with():
    movie = node("Movie", name="m")
    first = match(movie).with_(movie["title"].alias("title")).returning(name("title"))
    second = match(movie).with_(movie["released"].alias("year")).returning(name("year"))
    with pytest.raises(DslError, match="UNION projection"):
        union(first, second)


def test_union_parts_do_not_share_scope_state():
    movie = node("Movie", name="m")
    person = node("Person", name="p")
    left = match(movie).with_(movie).returning(movie["title"].alias("entry"))
    right = match(person).with_(person).returning(person["email"].alias("entry"))
    assert Renderer.get(Configuration(server_version="5.26")).render(union(left, right)).cypher == (
        "MATCH (m:Movie) WITH m RETURN m.title AS entry UNION MATCH (p:Person) WITH p RETURN p.email AS entry"
    )


def test_a_with_only_statement_cannot_be_a_union_part():
    movie = node("Movie", name="m")
    with pytest.raises(DslError, match="RETURN"):
        union(match(movie).with_(movie), returning(lit(1).alias("x")))


def test_union_requires_statements_or_statement_builders():
    with pytest.raises(DslError, match="UNION"):
        union(returning(lit(1)), "RETURN 2")  # type: ignore[arg-type]


def test_a_statement_with_a_with_and_no_return_cannot_be_rendered():
    movie = node("Movie", name="m")
    with pytest.raises(DslError, match="RETURN"):
        Renderer.get(Configuration(server_version="5.26")).render(match(movie).with_(movie))


def test_an_empty_builder_has_no_projection_to_finalise():
    with pytest.raises(DslError):
        StatementBuilder().build()

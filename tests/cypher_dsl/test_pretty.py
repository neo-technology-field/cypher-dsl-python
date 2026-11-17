"""Pretty rendering against the fixtures agreed in the design spec."""

from __future__ import annotations

from cypher_dsl import (
    Configuration,
    Language,
    Renderer,
    assign,
    desc,
    fn,
    match,
    merge,
    name,
    node,
    param,
    union,
)
from cypher_dsl.render.pretty import PrettyOccurrence, decide

RENDERER = Renderer.get(Configuration(server_version="5.26", pretty_print=True))


def test_pretty_print_is_accepted() -> None:
    assert Configuration(server_version="5.26", pretty_print=True).pretty_print is True


def test_a_statement_that_fits_stays_on_one_line() -> None:
    person = node("Person", name="p")
    statement = (
        match(person)
        .with_(person["uid"].alias("uid"))
        .where(person["rating"] > param("min_rating"))
        .returning(name("uid"))
    )
    assert RENDERER.render(statement).cypher == (
        "MATCH (p:Person) WITH p.uid AS uid WHERE p.rating > $min_rating RETURN uid"
    )


def test_a_statement_that_overflows_breaks_at_clause_boundaries() -> None:
    person = node("Person", name="p")
    statement = (
        match(person)
        .where((person["rating"] > param("min_rating")) & (person["email"] == param("email")))
        .returning(person["display_name"], person["rating"])
        .order_by(desc(person["rating"]))
        .skip(param("offset"))
        .limit(param("limit"))
    )
    assert RENDERER.render(statement).cypher == (
        "MATCH (p:Person)\n"
        "  WHERE p.rating > $min_rating AND p.email = $email\n"
        "RETURN p.display_name, p.rating\n"
        "  ORDER BY p.rating DESC SKIP $offset LIMIT $limit"
    )


def test_overflowing_modifiers_wrap_at_modifier_boundaries() -> None:
    person = node("Person", name="p")
    statement = (
        match(person)
        .returning(person["display_name"])
        .order_by(
            desc(person["display_name"]),
            desc(person["first_name"]),
            desc(person["last_name"]),
            desc(person["rating"]),
            desc(person["uid"]),
            desc(person["email"]),
        )
        .skip(param("offset"))
        .limit(param("limit"))
    )
    assert RENDERER.render(statement).cypher == (
        "MATCH (p:Person)\n"
        "RETURN p.display_name\n"
        "  ORDER BY p.display_name DESC, p.first_name DESC, p.last_name DESC,"
        " p.rating DESC, p.uid DESC, p.email DESC\n"
        "  SKIP $offset LIMIT $limit"
    )


def test_a_broken_with_filter_takes_its_own_indented_line() -> None:
    person = node("Person", name="p")
    statement = (
        match(person)
        .with_(
            person["uid"].alias("uid"),
            person["display_name"].alias("who"),
            person["rating"].alias("rating"),
        )
        .where((person["rating"] > param("min_rating")) & (person["email"] == param("email")))
        .returning(name("uid"), name("who"), name("rating"))
    )
    assert RENDERER.render(statement).cypher == (
        "MATCH (p:Person)\n"
        "WITH p.uid AS uid, p.display_name AS who, p.rating AS rating\n"
        "  WHERE p.rating > $min_rating AND p.email = $email\n"
        "RETURN uid, who, rating"
    )


def test_merge_actions_take_their_own_indented_lines() -> None:
    person = node("Person", name="p", properties={"email": param("email"), "uid": param("uid")})
    statement = (
        merge(person)
        .on_create(assign(person["created_at"], param("now")), assign(person["seen_at"], param("seen")))
        .on_match(assign(person["updated_at"], param("now")), assign(person["seen_count"], param("count")))
        .returning(person)
    )
    assert RENDERER.render(statement).cypher == (
        "MERGE (p:Person {email: $email, uid: $uid})\n"
        "  ON CREATE SET p.created_at = $now, p.seen_at = $seen\n"
        "  ON MATCH SET p.updated_at = $now, p.seen_count = $count\n"
        "RETURN p"
    )


def test_a_comma_list_that_overflows_wraps_greedily() -> None:
    person = node("Person", name="p")
    statement = match(person).returning(
        person["display_name"].alias("actor"),
        person["title"],
        person["rating"],
        person["tags"][0],
        person["tags"][param("index")],
        fn("coalesce", person["nickname"], "unknown"),
        fn("point.distance", person["here"], person["there"]),
    )
    assert RENDERER.render(statement).cypher == (
        "MATCH (p:Person)\n"
        "RETURN p.display_name AS actor, p.title, p.rating, p.tags[0], p.tags[$index],"
        " coalesce(p.nickname, 'unknown'),\n"
        "  point.distance(p.here, p.there)"
    )


def test_a_broken_union_renders_each_branch_clause_per_line() -> None:
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    statement = union(
        match(person).where(person["rating"] > param("min_rating")).returning(person["display_name"].alias("who")),
        match(movie).where(movie["released"] > param("since")).returning(movie["title"].alias("who")),
        all=True,
    )
    assert RENDERER.render(statement).cypher == (
        "MATCH (p:Person)\n"
        "  WHERE p.rating > $min_rating\n"
        "RETURN p.display_name AS who\n"
        "UNION ALL\n"
        "MATCH (m:Movie)\n"
        "  WHERE m.released > $since\n"
        "RETURN m.title AS who"
    )


def test_a_union_that_fits_stays_on_one_line() -> None:
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    statement = union(
        match(person).returning(person["uid"]),
        match(movie).returning(movie["uid"]),
    )
    assert RENDERER.render(statement).cypher == ("MATCH (p:Person) RETURN p.uid UNION MATCH (m:Movie) RETURN m.uid")


def test_a_union_whose_branch_holds_a_call_breaks() -> None:
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    body = match(person.relationship_to(movie, "ACTED_IN")).returning(movie["title"].alias("title")).build()
    statement = union(
        match(person).call(body, imports=("p",)).returning(name("title")),
        match(movie).returning(movie["title"].alias("title")),
    )
    assert RENDERER.render(statement).cypher == (
        "MATCH (p:Person)\n"
        "CALL (p) {\n"
        "  MATCH (p:Person)-[:ACTED_IN]->(m:Movie) RETURN m.title AS title\n"
        "}\n"
        "RETURN title\n"
        "UNION\n"
        "MATCH (m:Movie)\n"
        "RETURN m.title AS title"
    )


def test_a_union_that_fits_but_holds_a_call_still_breaks() -> None:
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    film = node("Film", name="f")
    body = match(movie).returning(movie["title"].alias("t")).build()
    statement = union(
        match(person).call(body).returning(name("t")),
        match(film).returning(film["title"].alias("t")),
    )
    assert RENDERER.render(statement).cypher == (
        "MATCH (p:Person)\n"
        "CALL () {\n"
        "  MATCH (m:Movie) RETURN m.title AS t\n"
        "}\n"
        "RETURN t\n"
        "UNION\n"
        "MATCH (f:Film)\n"
        "RETURN f.title AS t"
    )


def test_a_call_breaks_its_braces_even_when_the_statement_fits() -> None:
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    body = match(person.relationship_to(movie, "ACTED_IN")).returning(movie["title"].alias("title")).build()
    statement = match(person).call(body, imports=("p",)).returning(name("title"))
    assert RENDERER.render(statement).cypher == (
        "MATCH (p:Person)\n"
        "CALL (p) {\n"
        "  MATCH (p:Person)-[:ACTED_IN]->(m:Movie) RETURN m.title AS title\n"
        "}\n"
        "RETURN title"
    )


def test_a_call_body_that_overflows_renders_clause_per_line() -> None:
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    relationship = person.relationship_to(movie, "ACTED_IN", name="r")
    body = (
        match(relationship)
        .where(movie["released"] > param("since"))
        .returning(
            person["display_name"].alias("actor"),
            movie["title"],
            person["rating"],
            movie["released"],
        )
        .build()
    )
    statement = match(person).call(body, imports=("p",)).returning(name("actor"))
    assert RENDERER.render(statement).cypher == (
        "MATCH (p:Person)\n"
        "CALL (p) {\n"
        "  MATCH (p:Person)-[r:ACTED_IN]->(m:Movie)\n"
        "    WHERE m.released > $since\n"
        "  RETURN p.display_name AS actor, m.title, p.rating, m.released\n"
        "}\n"
        "RETURN actor"
    )


def test_an_oversized_expression_stays_on_one_line() -> None:
    person = node("Person", name="p")
    condition = person["a"] == param("one")
    for letter in "bcdefghijklmnopqrstuvwxyz":
        condition = condition & (person[letter] == param(letter))
    statement = match(person).where(condition).returning(person)
    lines = RENDERER.render(statement).cypher.splitlines()
    assert lines[0] == "MATCH (p:Person)"
    assert lines[1].startswith("  WHERE p.a = $one AND p.b = $b AND p.c = $c")
    assert lines[2] == "RETURN p"
    assert len(lines) == 3
    assert len(lines[1]) > 120


def test_the_language_prefix_takes_its_own_line() -> None:
    renderer = Renderer.get(Configuration(server_version="2026.10", language=Language.CYPHER_25, pretty_print=True))
    person = node("Person", name="p")
    statement = (
        match(person)
        .where((person["rating"] > param("min_rating")) & (person["email"] == param("email")))
        .returning(person["display_name"], person["rating"])
        .order_by(desc(person["rating"]))
        .skip(param("offset"))
        .limit(param("limit"))
    )
    assert renderer.render(statement).cypher.startswith("CYPHER 25\nMATCH (p:Person)\n")


def test_decide_assigns_levels_by_occurrence_path() -> None:
    person = node("Person", name="p")
    body = match(person).returning(person["uid"]).build()
    statement = match(person).call(body, import_all=True).returning(person).build()
    table = decide(statement, {})
    assert table[()] == PrettyOccurrence(True, 0)
    assert table[(0,)] == PrettyOccurrence(True, 0)
    assert table[(1,)] == PrettyOccurrence(True, 0)
    assert table[(1, 0, 0)] == PrettyOccurrence(False, 1)


def test_the_default_configuration_still_renders_compact_text() -> None:
    renderer = Renderer.get(Configuration(server_version="5.26"))
    person = node("Person", name="p")
    statement = (
        match(person)
        .where((person["rating"] > param("min_rating")) & (person["email"] == param("email")))
        .returning(person["display_name"], person["rating"])
        .order_by(desc(person["rating"]))
        .skip(param("offset"))
        .limit(param("limit"))
    )
    assert renderer.render(statement).cypher == (
        "MATCH (p:Person) WHERE p.rating > $min_rating AND p.email = $email"
        " RETURN p.display_name, p.rating ORDER BY p.rating DESC SKIP $offset LIMIT $limit"
    )

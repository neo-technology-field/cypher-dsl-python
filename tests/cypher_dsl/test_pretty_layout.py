"""The pretty occurrence layout renders each join kind with its break rule."""

from __future__ import annotations

from cypher_dsl.render.pretty import PrettyOccurrence


def test_tokens_and_series_never_break() -> None:
    occurrence = PrettyOccurrence(broken=True, level=2)
    assert occurrence.tokens("WHERE", "p.x > 1") == "WHERE p.x > 1"
    assert occurrence.series(["a", "b"]) == "a, b"


def test_listed_stays_flat_when_it_fits() -> None:
    occurrence = PrettyOccurrence(broken=True, level=0)
    assert occurrence.listed("RETURN", ["p.x", "p.y"]) == "RETURN p.x, p.y"


def test_listed_wraps_at_commas_with_two_space_continuation() -> None:
    occurrence = PrettyOccurrence(broken=True, level=0)
    item = "x" * 30
    expected = f"RETURN {item}, {item}, {item},\n  {item}, {item}, {item},\n  {item}"
    assert occurrence.listed("RETURN", [item] * 7) == expected


def test_listed_measures_the_start_column_from_the_occurrence_level() -> None:
    occurrence = PrettyOccurrence(broken=True, level=1)
    item = "x" * 113
    assert occurrence.listed("SET", [item, "y"]) == f"SET {item},\n    y"


def test_parenthesized_wraps_long_import_lists() -> None:
    occurrence = PrettyOccurrence(broken=True, level=0)
    name = "n" * 60
    assert occurrence.parenthesized("CALL", [name, name]) == f"CALL ({name},\n  {name})"


def test_owned_breaks_each_part_onto_its_own_indented_line() -> None:
    occurrence = PrettyOccurrence(broken=True, level=0)
    broken = occurrence.owned("MATCH (p)", "WHERE p.x > 1", "AND p.y < 2")
    assert broken == "MATCH (p)\n  WHERE p.x > 1\n  AND p.y < 2"
    flat = PrettyOccurrence(broken=False, level=0)
    assert flat.owned("MATCH (p)", "WHERE p.x > 1") == "MATCH (p) WHERE p.x > 1"


def test_packed_breaks_only_when_the_modifier_line_overflows() -> None:
    occurrence = PrettyOccurrence(broken=True, level=0)
    packed = occurrence.packed("RETURN p.x", "ORDER BY p.x", "SKIP 1")
    assert packed == "RETURN p.x\n  ORDER BY p.x SKIP 1"
    overflow = "ORDER BY " + "x" * 110
    wrapped = occurrence.packed("RETURN p.x", overflow, "SKIP 1")
    assert wrapped == f"RETURN p.x\n  {overflow}\n  SKIP 1"
    flat = PrettyOccurrence(broken=False, level=0)
    assert flat.packed("RETURN p.x", "SKIP 1") == "RETURN p.x SKIP 1"


def test_clauses_join_one_per_line_when_broken() -> None:
    occurrence = PrettyOccurrence(broken=True, level=1)
    assert occurrence.clauses(["MATCH (p)", "RETURN p"]) == "MATCH (p)\n  RETURN p"
    flat = PrettyOccurrence(broken=False, level=1)
    assert flat.clauses(["MATCH (p)", "RETURN p"]) == "MATCH (p) RETURN p"


def test_between_puts_the_union_keyword_on_its_own_line_when_broken() -> None:
    occurrence = PrettyOccurrence(broken=True, level=0)
    broken = occurrence.between(["MATCH (p) RETURN p", "MATCH (m) RETURN m"], "UNION ALL")
    assert broken == "MATCH (p) RETURN p\nUNION ALL\nMATCH (m) RETURN m"
    flat = PrettyOccurrence(broken=False, level=0)
    assert flat.between(["a", "b"], "UNION") == "a UNION b"


def test_body_indents_the_body_statement_and_closes_at_the_call_level() -> None:
    occurrence = PrettyOccurrence(broken=True, level=0)
    assert occurrence.body("CALL (p)", "MATCH (p) RETURN p") == "CALL (p) {\n  MATCH (p) RETURN p\n}"
    nested = PrettyOccurrence(broken=True, level=1)
    assert nested.body("CALL (p)", "MATCH (p) RETURN p") == "CALL (p) {\n    MATCH (p) RETURN p\n  }"


def test_listed_wraps_yield_items_under_a_composite_head() -> None:
    occurrence = PrettyOccurrence(broken=True, level=0)
    head = "CALL dbms.checkConfigValue($setting, $expected) YIELD"
    item = "x" * 30
    assert occurrence.listed(head, [item, item, item, item]) == f"{head} {item}, {item},\n  {item}, {item}"

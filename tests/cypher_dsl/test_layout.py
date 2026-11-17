"""The compact layout renders every join kind on one line."""

from __future__ import annotations

from cypher_dsl.render.context import RenderContext
from cypher_dsl.render.layout import COMPACT
from cypher_dsl.statements.frames import NoFacts


def test_compact_joins() -> None:
    assert COMPACT.tokens("RETURN", "m") == "RETURN m"
    assert COMPACT.series(["a", "b", "c"]) == "a, b, c"
    assert COMPACT.series([]) == ""
    assert COMPACT.listed("RETURN DISTINCT", ["a", "b"]) == "RETURN DISTINCT a, b"
    assert COMPACT.parenthesized("CALL", ["a", "b"]) == "CALL (a, b)"
    assert COMPACT.owned("MATCH (p)", "WHERE p.x") == "MATCH (p) WHERE p.x"
    assert COMPACT.packed("RETURN p", "SKIP 1") == "RETURN p SKIP 1"
    assert COMPACT.clauses(["MATCH (p)", "RETURN p"]) == "MATCH (p) RETURN p"
    assert COMPACT.between(["x", "y"], "UNION") == "x UNION y"
    assert COMPACT.body("CALL (p)", "RETURN p") == "CALL (p) { RETURN p }"


def test_context_defaults_to_compact() -> None:
    context = RenderContext(always_escape_names=False, facts=NoFacts())
    assert context.layout is COMPACT

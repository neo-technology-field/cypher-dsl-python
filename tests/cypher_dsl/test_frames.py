"""Frame values and the shared semantic vocabulary."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass

import pytest

from cypher_dsl import AstNode, Expression, Variable, match, name, node
from cypher_dsl.errors import DslError
from cypher_dsl.statements.frames import (
    ScopeFrame,
    free_variables_in,
    merge_names,
    reference_names,
    variables_in,
)
from cypher_dsl.statements.rules.base import check_references


def test_merge_names_keeps_first_declaration_order() -> None:
    assert merge_names(("p", "m"), ("m", "t")) == ("p", "m", "t")
    assert merge_names(()) == ()


def test_reference_names_follow_the_closed_flag() -> None:
    names = ("p",)
    assert reference_names(ScopeFrame(names)) is None
    assert reference_names(ScopeFrame(names, closed=True)) == names
    assert reference_names(ScopeFrame(None, closed=True)) is None


def test_variables_in_collects_variables_in_order() -> None:
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    collected = variables_in(match(person, movie).where(person["uid"] == movie["uid"]).clauses[0])
    assert [variable.symbol.value for variable in collected] == ["p", "m"]
    repeated = variables_in(person["uid"] == person["name"])
    assert [variable.symbol.value for variable in repeated] == ["p", "p"]


def test_scope_frame_defaults_are_uncertified_and_empty() -> None:
    frame = ScopeFrame()
    assert frame.names == ()
    assert frame.closed is False
    assert frame.certified is False
    assert frame.reserved == frozenset()
    assert frame.bindings == ()
    assert frame.unresolved == frozenset()


def test_scope_frame_is_frozen() -> None:
    frame = ScopeFrame(("p",), closed=True)
    with pytest.raises(FrozenInstanceError):
        frame.names = None  # type: ignore[misc]


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class _ComprehensionDouble(Expression):
    """Test double: binds one name for its subtree, the way a list comprehension will."""

    variable: Variable
    source: Expression
    projection: Expression

    def local_names(self) -> tuple[str, ...]:
        return (self.variable.symbol.value,)

    def children(self) -> tuple[AstNode, ...]:
        return (self.variable, self.source, self.projection)


def test_local_binding_is_not_a_free_reference() -> None:
    double = _ComprehensionDouble(name("x"), name("coll"), name("x")["uid"])
    assert [variable.symbol.value for variable in free_variables_in(double)] == ["coll"]


def test_variables_in_still_reports_every_variable() -> None:
    double = _ComprehensionDouble(name("x"), name("coll"), name("x")["uid"])
    assert [variable.symbol.value for variable in variables_in(double)] == ["x", "coll", "x"]


def test_check_references_accepts_local_bindings() -> None:
    double = _ComprehensionDouble(name("x"), name("coll"), name("x")["uid"])
    check_references((double,), ("coll",), "test")
    with pytest.raises(DslError, match="'coll'"):
        check_references((double,), (), "test")

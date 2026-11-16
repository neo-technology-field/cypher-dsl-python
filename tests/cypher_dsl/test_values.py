"""Frozen value ownership, literal factories and binding equivalence."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime, time, timedelta

import pytest

from cypher_dsl import (
    UNBOUND,
    Literal,
    Parameter,
    Variable,
    freeze_value,
    lit,
    name,
    param,
    same_binding,
    structurally_equal,
    thaw_value,
)
from cypher_dsl.errors import InvalidLiteralError


def test_lit_snapshots_mutable_input():
    original = {"values": [1, 2]}
    value = lit(original)
    original["values"].append(3)
    assert thaw_value(value.value) == {"values": [1, 2]}


def test_literal_value_cannot_be_replaced():
    value = lit([1, 2])
    with pytest.raises(FrozenInstanceError):
        value.value = freeze_value([])


def test_thawed_containers_are_independent_objects():
    value = lit({"values": [1, 2]})
    first = thaw_value(value.value)
    second = thaw_value(value.value)
    assert first == second
    assert first is not second
    assert first["values"] is not second["values"]


def test_frozen_values_retain_list_and_map_distinctions():
    thawed = thaw_value(lit([{"key": [1, 2]}]).value)
    assert isinstance(thawed, list)
    assert isinstance(thawed[0], dict)
    assert isinstance(thawed[0]["key"], list)


def test_sequences_thaw_as_lists_because_cypher_has_no_tuple_literal():
    assert thaw_value(freeze_value((1, 2))) == [1, 2]


def test_cyclic_list_input_is_rejected():
    values = []
    values.append(values)
    with pytest.raises(InvalidLiteralError, match="list"):
        lit(values)


def test_cyclic_mapping_input_is_rejected():
    values = {}
    values["self"] = values
    with pytest.raises(InvalidLiteralError, match="mapping"):
        lit(values)


def test_repeated_non_cyclic_subcontainers_are_allowed():
    shared = [1, 2]
    value = lit([shared, shared])
    assert thaw_value(value.value) == [[1, 2], [1, 2]]


def test_mapping_keys_must_be_strings():
    with pytest.raises(InvalidLiteralError, match="key"):
        lit({1: "value"})


def test_non_finite_floats_are_rejected():
    with pytest.raises(InvalidLiteralError, match="finite"):
        lit(float("inf"))


def test_unsupported_values_are_rejected():
    with pytest.raises(InvalidLiteralError, match="param"):
        lit(object())


def test_opaque_values_require_an_explicit_opt_in():
    marker = object()
    with pytest.raises(InvalidLiteralError):
        freeze_value(marker)
    assert thaw_value(freeze_value(marker, allow_opaque=True)) is marker


def test_parameter_keeps_unbound_apart_from_null():
    assert param("year").binding is UNBOUND
    assert param("year", None).binding is None


def test_parameter_snapshots_a_mutable_binding():
    original = [1]
    parameter = param("values", original)
    original.append(2)
    assert thaw_value(parameter.binding) == [1]


def test_factories_build_the_documented_nodes():
    assert isinstance(lit(1), Literal)
    assert isinstance(name("movie"), Variable)
    assert name("movie").symbol.value == "movie"
    assert isinstance(param("year"), Parameter)
    assert param("year").symbol.value == "year"


def test_temporal_values_round_trip():
    value = {
        "date": date(2024, 1, 2),
        "datetime": datetime(2024, 1, 2, 3, 4, 5),
        "time": time(3, 4, 5),
        "duration": timedelta(days=-1, seconds=2),
    }
    assert thaw_value(freeze_value(value)) == value


def test_same_binding_is_type_aware():
    assert same_binding(freeze_value(True), freeze_value(True))
    assert not same_binding(freeze_value(True), freeze_value(1))
    assert not same_binding(freeze_value(1), freeze_value(1.0))
    assert not same_binding(freeze_value("1"), freeze_value(b"1"))
    assert not same_binding(
        freeze_value(datetime(2024, 1, 2)),
        freeze_value(date(2024, 1, 2)),
    )


def test_same_binding_compares_containers_recursively():
    assert same_binding(freeze_value({"a": [1, 2]}), freeze_value({"a": [1, 2]}))
    assert not same_binding(freeze_value({"a": [1, 2]}), freeze_value({"a": [1, 3]}))
    assert same_binding(freeze_value({"a": 1, "b": 2}), freeze_value({"b": 2, "a": 1}))


def test_same_binding_never_uses_third_party_equality():
    class Explosive:
        def __eq__(self, other):
            raise AssertionError("opaque values must be compared by identity")

    first = Explosive()
    second = Explosive()
    assert same_binding(freeze_value(first, allow_opaque=True), freeze_value(first, allow_opaque=True))
    assert not same_binding(freeze_value(first, allow_opaque=True), freeze_value(second, allow_opaque=True))


def test_same_binding_rejects_an_empty_map_against_a_non_empty_map():
    empty = freeze_value({})
    populated = freeze_value({"x": 1})
    assert not same_binding(empty, populated)
    assert not same_binding(populated, empty)


def test_same_binding_rejects_a_proper_map_subset_in_both_orders():
    small = freeze_value({"x": 1})
    large = freeze_value({"x": 1, "y": 2})
    assert not same_binding(small, large)
    assert not same_binding(large, small)


def test_frozen_map_records_compare_symmetrically():
    empty = lit({}).value
    populated = lit({"x": 1}).value
    assert empty != populated
    assert populated != empty
    assert lit({"x": 1}).value != lit({"x": 1, "y": 2}).value
    assert lit({"x": 1, "y": 2}).value != lit({"x": 1}).value


def test_structural_comparison_rejects_unequal_map_cardinality_in_both_orders():
    assert not structurally_equal(lit({}), lit({"x": 1}))
    assert not structurally_equal(lit({"x": 1}), lit({}))
    assert not structurally_equal(lit({"x": 1}), lit({"x": 1, "y": 2}))
    assert not structurally_equal(lit({"x": 1, "y": 2}), lit({"x": 1}))


class _ExplosiveInt(int):
    def __eq__(self, other):
        raise AssertionError("third-party scalar equality called")


class _ExplosiveDate(date):
    def __eq__(self, other):
        raise AssertionError("third-party temporal equality called")


_EXPLOSIVE_SCALARS = [
    lambda: _ExplosiveInt(10),
    lambda: _ExplosiveDate(2024, 1, 2),
]


@pytest.mark.parametrize("factory", _EXPLOSIVE_SCALARS)
def test_scalar_subclasses_are_not_literals(factory):
    with pytest.raises(InvalidLiteralError):
        lit(factory())


@pytest.mark.parametrize("factory", _EXPLOSIVE_SCALARS)
def test_scalar_subclasses_are_identity_only_bindings(factory):
    first, second = factory(), factory()
    assert thaw_value(freeze_value(first, allow_opaque=True)) is first
    assert same_binding(freeze_value(first, allow_opaque=True), freeze_value(first, allow_opaque=True))
    assert not same_binding(freeze_value(first, allow_opaque=True), freeze_value(second, allow_opaque=True))

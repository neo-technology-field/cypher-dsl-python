"""Python operators, predicates, properties, subscripts and raw expressions."""

from __future__ import annotations

import pytest

from cypher_dsl import (
    BinaryOperation,
    Comparison,
    Condition,
    Configuration,
    Property,
    Renderer,
    SubscriptExpression,
    SymbolicName,
    UnaryOperation,
    boolean_operation,
    condition,
    in_,
    lit,
    name,
    param,
    raw,
    returning,
)
from cypher_dsl.errors import DslError


def _render(value):
    return Renderer.get(Configuration(server_version="5.26")).render(returning(value)).cypher


@pytest.mark.parametrize("operation", [lambda value: bool(value), lambda value: 1 < value < 3])
def test_python_boolean_evaluation_is_rejected(operation):
    with pytest.raises(TypeError, match="boolean"):
        operation(name("x"))


def test_reflected_arithmetic_preserves_precedence():
    value = (10 - name("x")) * (name("y") + 2)
    assert _render(value) == "RETURN (10 - x) * (y + 2)"


def test_null_comparisons_are_predicates():
    value = name("x")
    query = returning((value == None).alias("missing"), (value != None).alias("present"))  # noqa: E711
    rendered = Renderer.get(Configuration(server_version="5.26")).render(query)
    assert rendered.cypher == "RETURN x IS NULL AS missing, x IS NOT NULL AS present"
    assert isinstance(value == lit(1), Condition)


def test_comparisons_build_conditions():
    value = name("x")
    assert isinstance(value == 1, Comparison)
    assert isinstance(value != 1, Comparison)
    assert isinstance(value < 1, Comparison)
    assert isinstance(value <= 1, Comparison)
    assert isinstance(value > 1, Comparison)
    assert isinstance(value >= 1, Comparison)


def test_comparison_values_stay_literals():
    assert _render(name("x") == "movie") == "RETURN x = 'movie'"
    assert _render(name("x") != 1) == "RETURN x <> 1"


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        (lambda value: 2 + value, "2 + x"),
        (lambda value: 2 - value, "2 - x"),
        (lambda value: 2 * value, "2 * x"),
        (lambda value: 2 / value, "2 / x"),
        (lambda value: 2 % value, "2 % x"),
    ],
)
def test_reflected_arithmetic_keeps_the_left_operand(operation, expected):
    assert _render(operation(name("x"))) == f"RETURN {expected}"


def test_arithmetic_grouping_follows_precedence_and_tree_shape():
    x, y, z = name("x"), name("y"), name("z")
    assert _render(x - y - z) == "RETURN x - y - z"
    assert _render(x - (y - z)) == "RETURN x - (y - z)"
    assert _render(x / (y * z)) == "RETURN x / (y * z)"
    assert _render((x / y) * z) == "RETURN x / y * z"
    assert _render(x % 2 + 1) == "RETURN x % 2 + 1"
    assert _render(-x * 2) == "RETURN -x * 2"
    assert _render(-(x + 1)) == "RETURN -(x + 1)"
    assert _render(+x) == "RETURN +x"
    assert _render(-lit(1)) == "RETURN -1"


def test_arithmetic_nodes_keep_their_operator():
    assert isinstance(name("x") + 1, BinaryOperation)
    assert (name("x") + 1).operator == "+"
    assert isinstance(-name("x"), UnaryOperation)
    assert (-name("x")).operator == "-"


def test_comparison_operands_group_lower_precedence_arithmetic():
    x = name("x")
    assert _render(x > 1) == "RETURN x > 1"
    assert _render(x > (name("y") + 1)) == "RETURN x > y + 1"
    assert _render((x > 1) == lit(True)) == "RETURN (x > 1) = true"


def test_boolean_operations_group_by_precedence():
    a, b, c = name("a"), name("b"), name("c")
    combined = (a > 1) & ((b < 2) | (c == "value"))
    assert isinstance(combined, Condition)
    assert _render(combined) == "RETURN a > 1 AND (b < 2 OR c = 'value')"
    alternative = (a > 1) | ((b < 2) & (c > 3))
    assert isinstance(alternative, Condition)
    assert _render(alternative) == "RETURN a > 1 OR b < 2 AND c > 3"


def test_negation_wraps_only_lower_precedence_operands():
    a, b = name("a"), name("b")
    assert _render(~(a > 1)) == "RETURN NOT a > 1"
    assert _render(~((a > 1) & (b < 2))) == "RETURN NOT (a > 1 AND b < 2)"
    assert isinstance(~(a > 1), UnaryOperation)
    assert _render(~~(a > 1)) == "RETURN NOT NOT a > 1"


def _negate(value):
    return -value


def _positive(value):
    return +value


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        (lambda value: _negate(_negate(value)), "-(-x)"),
        (lambda value: _positive(_positive(value)), "+(+x)"),
        (lambda value: _negate(_positive(value)), "-(+x)"),
        (lambda value: _positive(_negate(value)), "+(-x)"),
    ],
)
def test_nested_unary_arithmetic_is_grouped(operation, expected):
    assert _render(operation(name("x"))) == f"RETURN {expected}"


def test_deeply_nested_unary_arithmetic_is_grouped():
    assert _render(_negate(_negate(_negate(name("x"))))) == "RETURN -(-(-x))"


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        (lambda value: value < None, "x < null"),
        (lambda value: value <= None, "x <= null"),
        (lambda value: value > None, "x > null"),
        (lambda value: value >= None, "x >= null"),
    ],
)
def test_ordering_against_null_is_a_cypher_comparison(operation, expected):
    assert _render(operation(name("x"))) == f"RETURN {expected}"


def test_implicit_and_explicit_null_ordering_operands_agree():
    assert _render(name("x") < None) == _render(name("x") < lit(None)) == "RETURN x < null"


def test_boolean_operation_rejects_unknown_logical_operators():
    with pytest.raises(DslError, match="logical operator"):
        boolean_operation("XOR", condition(name("a")), condition(name("b")))


def test_unary_operation_is_arithmetic_only():
    from cypher_dsl.expressions.operators import unary_operation

    with pytest.raises(DslError, match="negate"):
        unary_operation("NOT", name("a"))


def test_condition_wraps_explicitly_boolean_values():
    flag = name("flag")
    wrapped = condition(flag)
    assert isinstance(wrapped, Condition)
    assert wrapped is not flag
    assert _render(wrapped) == "RETURN flag"
    predicate = flag > 1
    assert condition(predicate) is predicate


def test_condition_values_cannot_be_evaluated_as_booleans():
    with pytest.raises(TypeError, match="boolean"):
        bool(condition(name("flag")))


def test_in_renders_membership():
    membership = in_(name("x"), ["a", "b"])
    assert isinstance(membership, Condition)
    assert _render(membership) == "RETURN x IN ['a', 'b']"


def test_static_property_access_is_a_named_property():
    entry = name("entry")
    uid = entry["uid"]
    assert isinstance(uid, Property)
    assert uid.key == SymbolicName("uid")
    assert _render(uid) == "RETURN entry.uid"
    assert _render(entry["home.location"]) == "RETURN entry.`home.location`"
    assert _render(entry["uid"]["extra"]) == "RETURN entry.uid.extra"


def test_integer_indexing_is_a_subscript():
    entry = name("entry")
    first = entry[0]
    assert isinstance(first, SubscriptExpression)
    assert _render(first) == "RETURN entry[0]"


def test_dynamic_property_keys_stay_syntax():
    rendered = Renderer.get(Configuration(server_version="5.26")).render(returning(name("entry")[param("key")]))
    assert rendered.cypher == "RETURN entry[$key]"
    assert rendered.unbound_parameters == frozenset({"key"})


def test_expression_subscripts_are_not_string_interpolation():
    assert _render(name("entry")[name("ordinal")]) == "RETURN entry[ordinal]"
    assert _render(name("entry")[name("odd index")]) == "RETURN entry[`odd index`]"


def test_property_access_groups_a_lower_precedence_base():
    assert _render((name("a") + name("b"))["uid"]) == "RETURN (a + b).uid"


def test_aliases_keep_embedded_backticks():
    assert _render(name("n").alias("odd`name")) == "RETURN n AS `odd``name`"


def test_aliased_expressions_are_not_operands():
    with pytest.raises(DslError, match="alias"):
        name("x").alias("projected") + 1
    with pytest.raises(DslError, match="alias"):
        name("x").alias("projected")["value"]


def test_raw_expressions_are_opaque_and_lowest_precedence():
    trusted = raw("a + b")
    assert _render(trusted) == "RETURN a + b"
    assert _render(trusted > 1) == "RETURN (a + b) > 1"
    assert _render(name("x") + raw("y % 2")) == "RETURN x + (y % 2)"

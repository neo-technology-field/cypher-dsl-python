"""
Names, literals, parameters, projections and the frozen value representation.

A literal owns an immutable snapshot of the Python value it was built from. Callers
keep their own containers and may mutate them afterwards. A bound parameter can also
carry an object the library cannot inspect, such as a driver-specific type: that object
is kept by identity, never copied, and the caller must not mutate it during rendering.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from math import isfinite
from typing import ClassVar, Final, TypeAlias, cast

from cypher_dsl.errors import DslError, InvalidIdentifierError, InvalidLiteralError
from cypher_dsl.expressions.base import Expression, ExpressionInput, LiteralInput, coerce_expression, require_operand
from cypher_dsl.ast import AstNode

FrozenScalar: TypeAlias = bool | int | float | str | bytes | date | datetime | time | timedelta | None

_EXACT_SCALAR_TYPES: Final = (type(None), bool, int, float, str, bytes, date, datetime, time, timedelta)


@dataclass(frozen=True, weakref_slot=True, slots=True)
class SymbolicName:
    """
    A Cypher name used for variables and parameters.

    Normal Python equality is intentional here. Two references to ``movie`` denote the
    same name, and the value object carries no syntax tree of its own.
    """

    value: str


_ENCODED_ESCAPE: Final = re.compile(r"\\([uU])([0-9a-fA-F]{4,8})")


def validate_name(value: str) -> None:
    """
    Reject a name that no identifier position can carry.

    Validation happens where a name enters the syntax tree, so a pattern cannot carry a
    control character until a caller happens to render it. Encoded escapes are refused
    rather than decoded because Cypher interprets ``\\u0060`` as a backtick, which would
    let a name end its own quoting.

    Quoting shape and reserved-word decisions stay with the renderer. ``count`` is a
    legal function name and an illegal bare variable, so those decisions need the
    rendering context rather than this check.

    Args:
        value: Candidate name for a variable, label, relationship type or property key.

    Raises:
        InvalidIdentifierError: If the name is empty, contains a control character,
            contains an encoded escape sequence, or decodes to a control character.
    """
    if not value:
        raise InvalidIdentifierError("An identifier cannot be empty.")
    for character in value:
        code_point = ord(character)
        if code_point < 0x20 or code_point == 0x7F:
            raise InvalidIdentifierError(
                f"Identifier {value!r} contains prohibited control character U+{code_point:04X}."
            )
    _reject_encoded_escapes(value)


def _reject_encoded_escapes(value: str) -> None:
    for match in _ENCODED_ESCAPE.finditer(value):
        digits = match.group(2)
        width = 8 if match.group(1) == "U" and len(digits) >= 8 else 4
        decoded = int(digits[:width], 16)
        if decoded < 0x20 or decoded == 0x7F:
            raise InvalidIdentifierError(
                f"Identifier {value!r} decodes to prohibited control character U+{decoded:04X}. "
                "Pass the literal character instead of an escape sequence."
            )
        raise InvalidIdentifierError(
            f"Identifier {value!r} contains the Cypher escape sequence {match.group(0)!r}. "
            "Identifiers are data, not query text. Pass the literal character instead."
        )


class _Unbound:
    """
    Sentinel type for a parameter that has no binding yet.

    A distinct type keeps an unbound occurrence apart from a parameter bound to null,
    which is a real value that must still be rendered and sent to the server.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNBOUND"


UNBOUND: Final = _Unbound()

Unbound: TypeAlias = _Unbound


class _FrozenRecord:
    """
    Base for unhashable frozen value records.

    Each record defines value equality for the representation it owns. Hashing stays
    disabled because an identity hash would disagree with that equality.
    """

    __slots__ = ()

    __hash__: ClassVar[None] = None  # type: ignore[assignment]


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class _FrozenList(_FrozenRecord):
    """Immutable snapshot of a list-like literal value."""

    items: tuple[FrozenValue, ...]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _FrozenList):
            return NotImplemented
        return len(self.items) == len(other.items) and all(
            same_binding(left, right) for left, right in zip(self.items, other.items, strict=True)
        )


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class _FrozenMap(_FrozenRecord):
    """Immutable snapshot of a string-keyed mapping literal, in source order."""

    entries: tuple[tuple[str, FrozenValue], ...]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _FrozenMap):
            return NotImplemented
        return _frozen_maps_equal(self, other)


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class _OpaqueValue(_FrozenRecord):
    """
    Caller-owned binding value that the library keeps by identity only.

    The wrapper exists so that no comparison path reaches the third-party ``__eq__`` of
    a driver object. Two distinct objects never compare equal, even if their own
    equality says otherwise.
    """

    value: object

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _OpaqueValue):
            return NotImplemented
        return self.value is other.value


# Built when the module is imported, so it sits below the record classes it names.
FrozenValue: TypeAlias = FrozenScalar | _FrozenList | _FrozenMap | _OpaqueValue


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class Literal(Expression):
    """A Cypher literal whose value was frozen when the node was built."""

    value: FrozenValue


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class Variable(Expression):
    """A reference to a name bound elsewhere in the statement."""

    symbol: SymbolicName


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class Parameter(Expression):
    """
    An explicit query parameter occurrence.

    The binding is either a frozen value or ``UNBOUND``. Visibility of the parameter to
    the caller is decided per render, not stored on the node, so the same tree can be
    rendered with different bindings without mutation.
    """

    symbol: SymbolicName
    binding: FrozenValue | Unbound


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class AliasedExpression(Expression):
    """
    An expression projected under another name.

    Aliasing is a syntax node rather than a name field on the expression, so the same
    expression can be projected under several names without one projection changing
    another. The alias stays a name value and is quoted when rendered.

    Attributes:
        expression: The expression being projected.
        alias_name: Result name. It cannot be called ``alias`` because that name is the
            projection method inherited from :class:`Expression`.
    """

    expression: Expression
    alias_name: SymbolicName

    def __post_init__(self) -> None:
        """
        Reject a nested alias, which would render two ``AS`` words for one item.

        Raises:
            DslError: If the wrapped expression is itself an aliased projection. The
                caller should alias the underlying expression once.
        """
        if isinstance(self.expression, AliasedExpression):
            raise DslError("A projection cannot be aliased twice. Alias the underlying expression once.")

    def children(self) -> tuple[AstNode, ...]:
        """Expose the aliased expression as the only child."""
        return (self.expression,)


class SortOrder(Enum):
    """Direction attached to an ordering item."""

    ASCENDING = "ASC"
    DESCENDING = "DESC"


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class SortItem(AstNode):
    """
    An ordering item: an expression and an explicit direction.

    A bare expression is not wrapped, so ascending order can be requested without
    rendering a redundant ``ASC`` token. Callers that want the token use :func:`asc`.

    Attributes:
        expression: Sort key.
        direction: Explicit ordering direction.
    """

    expression: Expression
    direction: SortOrder

    def __post_init__(self) -> None:
        """Reject an alias, which is a projection rather than a sort key."""
        require_operand(self.expression)

    def children(self) -> tuple[AstNode, ...]:
        """Expose the sort key."""
        return (self.expression,)


def asc(expression: ExpressionInput) -> SortItem:
    """Order an expression ascending."""
    return SortItem(coerce_expression(expression), SortOrder.ASCENDING)


def desc(expression: ExpressionInput) -> SortItem:
    """Order an expression descending."""
    return SortItem(coerce_expression(expression), SortOrder.DESCENDING)


def lit(value: LiteralInput) -> Literal:
    """
    Build a literal expression from a Python value.

    Args:
        value: Data accepted by ``LiteralInput``. Mutable containers are snapshotted.

    Returns:
        A literal node that no longer observes later changes to the input containers.

    Raises:
        InvalidLiteralError: If the value is unsupported, has a non-string map key,
            uses a non-finite float, or contains a cyclic container.
    """
    return Literal(freeze_value(value))


def name(variable_name: str) -> Variable:
    """Build a variable reference from its name."""
    return Variable(SymbolicName(variable_name))


def param(parameter_name: str, value: object = UNBOUND) -> Parameter:
    """
    Build an explicit parameter occurrence.

    Args:
        parameter_name: Name used in the rendered ``$name`` placeholder.
        value: Binding value, or ``UNBOUND`` for a parameter resolved elsewhere.

    Returns:
        A parameter node with a frozen binding, or an unbound occurrence.

    Raises:
        InvalidLiteralError: If a supplied binding cannot be represented.
    """
    if value is UNBOUND:
        return Parameter(SymbolicName(parameter_name), UNBOUND)
    return Parameter(SymbolicName(parameter_name), freeze_value(value, allow_opaque=True))


def freeze_value(value: object, allow_opaque: bool = False) -> FrozenValue:
    """
    Snapshot a Python value into the immutable representation used by syntax.

    Known scalars and temporal values are kept as they are. Lists, tuples and other
    sequences become frozen lists, string-keyed mappings become frozen maps, and both
    keep their list or map identity so rendering never has to guess.

    Args:
        value: Value to snapshot.
        allow_opaque: Keep an unsupported object by identity instead of rejecting it.

    Returns:
        A frozen value. Thaw it with ``thaw_value`` to obtain fresh containers.

    Raises:
        InvalidLiteralError: If the value is unsupported while ``allow_opaque`` is
            false, a map key is not a string, a float is not finite, or a container
            takes part in a cycle.
    """
    return _freeze(value, allow_opaque, frozenset())


def _freeze(value: object, allow_opaque: bool, active: frozenset[int]) -> FrozenValue:
    if type(value) in _EXACT_SCALAR_TYPES:
        if type(value) is float and not isfinite(value):
            raise InvalidLiteralError(f"Non-finite float {value!r} is not a valid Cypher literal.")
        return cast(FrozenScalar, value)
    if isinstance(value, Mapping):
        if id(value) in active:
            raise InvalidLiteralError("Cyclic mapping cannot be frozen as a literal.")
        nested = active | {id(value)}
        entries: list[tuple[str, FrozenValue]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvalidLiteralError(f"Map literal keys must be strings, got {type(key).__name__}.")
            entries.append((key, _freeze(item, allow_opaque, nested)))
        return _FrozenMap(tuple(entries))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if id(value) in active:
            raise InvalidLiteralError("Cyclic list cannot be frozen as a literal.")
        nested = active | {id(value)}
        return _FrozenList(tuple(_freeze(item, allow_opaque, nested) for item in value))
    if allow_opaque:
        return _OpaqueValue(value)
    raise InvalidLiteralError(
        f"Unsupported literal value of type {type(value).__name__}. Use param() to bind it instead."
    )


def thaw_value(value: FrozenValue) -> object:
    """
    Return an independent Python value for a frozen value.

    Containers are rebuilt on every call, so a caller can mutate the result without
    touching the syntax tree. Opaque bindings are returned as the original object.
    """
    if isinstance(value, _FrozenList):
        return [thaw_value(item) for item in value.items]
    if isinstance(value, _FrozenMap):
        return {key: thaw_value(item) for key, item in value.entries}
    if isinstance(value, _OpaqueValue):
        return value.value
    return value


def same_binding(left: FrozenValue, right: FrozenValue) -> bool:
    """
    Compare two frozen values with binding-equivalence rules.

    Identical objects match. Otherwise both types must match, so ``True`` and ``1`` or an
    integer and a float are different bindings. Known containers are compared
    recursively. Opaque objects only match by identity, which prevents a driver object's
    own equality from deciding whether two declarations conflict.
    """
    if left is right:
        return True
    if type(left) is not type(right):
        return False
    if isinstance(left, _FrozenList) and isinstance(right, _FrozenList):
        return len(left.items) == len(right.items) and all(
            same_binding(left_item, right_item) for left_item, right_item in zip(left.items, right.items, strict=True)
        )
    if isinstance(left, _FrozenMap) and isinstance(right, _FrozenMap):
        return _frozen_maps_equal(left, right)
    if isinstance(left, _OpaqueValue) and isinstance(right, _OpaqueValue):
        return left.value is right.value
    if type(left) in _EXACT_SCALAR_TYPES:
        return left == right
    return False


def _frozen_maps_equal(left: _FrozenMap, right: _FrozenMap) -> bool:
    """
    Compare frozen maps by key set and recursive value equivalence.

    The key sets are compared before any value, so an empty map never matches a
    populated one and a proper subset never matches its superset, regardless of which
    argument is on the left.
    """
    left_entries = dict(left.entries)
    right_entries = dict(right.entries)
    if len(left_entries) != len(left.entries) or len(right_entries) != len(right.entries):
        return False
    if left_entries.keys() != right_entries.keys():
        return False
    return all(same_binding(value, right_entries[key]) for key, value in left_entries.items())


__all__ = [
    "UNBOUND",
    "AliasedExpression",
    "FrozenValue",
    "Literal",
    "Parameter",
    "SortItem",
    "SortOrder",
    "SymbolicName",
    "Unbound",
    "Variable",
    "asc",
    "desc",
    "freeze_value",
    "lit",
    "name",
    "param",
    "same_binding",
    "thaw_value",
    "validate_name",
]

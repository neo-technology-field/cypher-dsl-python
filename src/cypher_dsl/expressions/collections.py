"""
List and map expressions whose entries stay child syntax.

A collection expression is not a frozen literal. Its entries are expression nodes, so a
nested parameter, property read or subscript is visited and rendered as syntax instead of
being flattened into text. Maps keep the caller's insertion order because that order is
part of the rendered output.

These nodes deliberately duplicate neither ``Literal`` nor a pattern's property map. A
literal owns data, a pattern map is not an expression, and a map expression is a value
that can be assigned, returned or passed to a function.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from cypher_dsl.ast import AstNode, _require_tuple
from cypher_dsl.errors import DslError
from cypher_dsl.expressions.base import Expression, ExpressionInput, coerce_expression, require_operand
from cypher_dsl.expressions.values import SymbolicName, validate_name

MapEntry = tuple[SymbolicName, Expression]


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class ListExpression(Expression):
    """
    A list expression rendered as ``[item, ...]``.

    An empty list is a legal Cypher value, so the item collection may be empty. The
    items are ordered exactly as the caller supplied them.

    Attributes:
        items: Item expressions in rendered order.
    """

    items: tuple[Expression, ...]

    def __post_init__(self) -> None:
        """Reject a non-tuple collection, an alias item or a non-expression item."""
        _require_tuple(self.items, "List expression items")
        for item in self.items:
            if not isinstance(item, Expression):
                raise DslError(f"A list expression item must be an expression, not {type(item).__name__}.")
            require_operand(item)

    def children(self) -> tuple[AstNode, ...]:
        """Expose the items in rendered order."""
        return self.items


@dataclass(frozen=True, eq=False, weakref_slot=True, slots=True)
class MapExpression(Expression):
    """
    A map expression rendered as ``{key: value, ...}``.

    Keys are names, not data, so they are quoted with the identifier rules. Values are
    expressions, which is what makes ``{uid: row.uid}`` possible without interpolating
    the read. An empty map is legal, and duplicate keys are rejected because one key
    cannot stand for two values.

    Attributes:
        entries: Key and value pairs in the caller's insertion order.
    """

    entries: tuple[MapEntry, ...]

    def __post_init__(self) -> None:
        """
        Reject an invalid collection, key, duplicate key or value.

        Raises:
            DslError: If the collection is not a tuple of pairs, a key is not a name, a
                key repeats, or a value is not an expression or is an alias.
            InvalidIdentifierError: If a key fails name validation.
        """
        _require_tuple(self.entries, "Map expression entries")
        seen: set[str] = set()
        for entry in self.entries:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise DslError("A map expression entry must be a key and value pair.")
            key, value = entry
            if not isinstance(key, SymbolicName):
                raise DslError(f"A map expression key must be a name, not {type(key).__name__}.")
            validate_name(key.value)
            if key.value in seen:
                raise DslError(f"Duplicate key {key.value!r} in a map expression.")
            seen.add(key.value)
            if not isinstance(value, Expression):
                raise DslError(f"A map expression value must be an expression, not {type(value).__name__}.")
            require_operand(value)

    def children(self) -> tuple[AstNode, ...]:
        """Expose the values in rendered order, matching ``entries``."""
        return tuple(value for _, value in self.entries)

    @classmethod
    def from_mapping(cls, items: Mapping[str, ExpressionInput]) -> MapExpression:
        """
        Snapshot a caller's mapping into typed entries.

        Args:
            items: String keys and expression or literal values. A bare string stays a
                literal value, which keeps data and names separate.

        Returns:
            A map expression that no longer observes later changes to ``items``.

        Raises:
            DslError: If a key is not a string.
        """
        entries: list[MapEntry] = []
        for key, value in items.items():
            if not isinstance(key, str):
                raise DslError(f"Map expression keys must be strings, not {type(key).__name__}.")
            entries.append((SymbolicName(key), coerce_expression(value)))
        return cls(tuple(entries))


def list_(*items: ExpressionInput) -> ListExpression:
    """
    Build a list expression from ordered items.

    Args:
        items: Items to place in the list. An empty call renders ``[]``, which is a valid
            Cypher value rather than an incomplete construct.

    Returns:
        A list expression whose contents are child syntax.

    Raises:
        DslError: If an item is an aliased projection.
        InvalidLiteralError: If an item cannot become a literal.
    """
    expressions = tuple(coerce_expression(item) for item in items)
    return ListExpression(expressions)


def map_(items: Mapping[str, ExpressionInput]) -> MapExpression:
    """
    Build a map expression from a string-keyed mapping.

    Args:
        items: Keys and values. Insertion order is preserved. Values may be expressions
            such as ``row["uid"]``.

    Returns:
        A map expression whose contents are child syntax.

    Raises:
        DslError: If the argument is not a mapping, a key is not a string, or a value is
            an aliased projection.
        InvalidLiteralError: If a value cannot become a literal.
    """
    if not isinstance(items, Mapping):
        raise DslError(f"map_ needs a string-keyed mapping, not {type(items).__name__}.")
    return MapExpression.from_mapping(items)


__all__ = ["ListExpression", "MapExpression", "list_", "map_"]

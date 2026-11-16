"""
Type aliases are typing objects, not strings.

An alias whose value is a string is a value rather than a type. Callers that resolve
annotations programmatically then fail, and static tools disagree about what the
annotation means. These tests pin the aliases to objects that can be resolved.
"""

from __future__ import annotations

import typing

import cypher_dsl
from cypher_dsl import Literal, Parameter, asc, desc, lit
from cypher_dsl.clauses.projection import OrderItem, ProjectionOwner
from cypher_dsl.clauses.write import Update
from cypher_dsl.expressions.values import FrozenScalar, Unbound
from cypher_dsl.render.renderer import RenderInput

# Aliases that are not part of the public surface still describe signatures, so they are
# held to the same rule.
_INTERNAL_ALIASES = (OrderItem, Update, ProjectionOwner, RenderInput, FrozenScalar, Unbound)


def test_aliases_are_types_not_strings():
    exported = [getattr(cypher_dsl, name) for name in cypher_dsl.__all__]
    for alias in (*exported, *_INTERNAL_ALIASES):
        assert not isinstance(alias, str), f"{alias!r} is a string, not a type"


def test_annotations_resolve_to_types():
    for annotated in (lit, asc, desc, Literal, Parameter):
        assert typing.get_type_hints(annotated) != {}

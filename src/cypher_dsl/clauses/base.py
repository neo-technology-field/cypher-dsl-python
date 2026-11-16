"""
Clause base type.

A clause is a syntax node with a fixed position in a statement.
"""

from __future__ import annotations

from cypher_dsl.syntax import AstNode


class Clause(AstNode):
    """
    Base for a clause that occupies one position in an ordered statement.

    Subclasses hold their own contents as frozen fields and expose those contents as
    children in rendered order.
    """

    __slots__ = ()


__all__ = ["Clause"]

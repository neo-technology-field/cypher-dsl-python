"""
How one render joins fragment text.

Compose functions join child text through these verbs instead of embedding separator
literals, so the layout decision lives in one type. Each verb names the kind of join a
site performs: ``tokens`` and ``series`` join inside one expression and never break,
``listed`` and ``parenthesized`` join a clause head and its items and wrap when
overflowing, ``owned`` and ``packed`` append the sub-clauses a clause owns, ``clauses``
joins the clauses of one statement, ``between`` joins union branches and ``body`` joins
a subquery header (``CALL`` or ``EXISTS``), its body statement and the closing brace. The
compact layout renders every join on one line; the pretty layout in ``render/pretty.py``
is a second implementation of the same verbs, not an edit per construct. Sites that are
not fragment joins -- unary-minus adjacency, colon-joined labels, literal rendering --
never call these verbs.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final


class Layout:
    """The joins a render uses between fragments."""

    __slots__ = ()

    def tokens(self, *parts: str) -> str:
        """Join the tokens of one construct with spaces. Never breaks."""
        return " ".join(parts)

    def series(self, parts: Iterable[str]) -> str:
        """Join the items of a comma-separated list inside one expression. Never breaks."""
        return ", ".join(parts)

    def listed(self, head: str, parts: Iterable[str]) -> str:
        """Join a clause head and its comma-separated items. Wraps when overflowing."""
        return f"{head} {', '.join(parts)}"

    def parenthesized(self, keyword: str, parts: Iterable[str]) -> str:
        """Join a keyword and a parenthesized, comma-separated list. Wraps when overflowing."""
        return f"{keyword} ({', '.join(parts)})"

    def owned(self, text: str, *parts: str) -> str:
        """Append the sub-clauses a clause owns, each on its own indented line when broken."""
        return " ".join((text, *parts))

    def packed(self, text: str, *parts: str) -> str:
        """Append owned modifier segments, packed onto one indented line when broken."""
        return " ".join((text, *parts))

    def clauses(self, parts: Iterable[str]) -> str:
        """Join the clauses of one statement. One clause per line when broken."""
        return " ".join(parts)

    def between(self, parts: Iterable[str], keyword: str) -> str:
        """Join union branches around a keyword, such as ``UNION``."""
        return f" {keyword} ".join(parts)

    def body(self, header: str, inner: str) -> str:
        """Join a subquery header, its body statement and the closing brace."""
        return f"{header} {{ {inner} }}"


COMPACT: Final = Layout()


__all__ = ["COMPACT", "Layout"]

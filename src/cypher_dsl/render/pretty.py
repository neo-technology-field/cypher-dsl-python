"""
The pretty layout and the walks that select it per occurrence.

A pretty render joins the same fragments as a compact render through the same verbs,
but each breakable occurrence composes through one ``PrettyOccurrence`` holding its
break mode and indent level. The width is fixed: pretty output exists for reading in
logs and terminals, and a caller who needs a different width formats the compact
output outside the library. The decision walk below is the single place the pretty
policy lives: which occurrences may break and at what indent level. Nothing in the
rule modules knows about it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from cypher_dsl.ast import AstNode, OccurrencePath, _Visitor
from cypher_dsl.clauses.base import Clause
from cypher_dsl.clauses.call import SubqueryCallClause
from cypher_dsl.clauses.match import Where
from cypher_dsl.clauses.write import MergeAction
from cypher_dsl.expressions.subqueries import ExistsExpression
from cypher_dsl.render.layout import COMPACT, Layout
from cypher_dsl.render.rules import RenderingRules
from cypher_dsl.render.traversal import RenderingTraversal
from cypher_dsl.statements.analysis import Analysis
from cypher_dsl.statements.composition import Statement, UnionStatement

WIDTH = 120
INDENT_WIDTH = 2


def _pad(level: int) -> str:
    """Return the indentation of one level."""
    return " " * (INDENT_WIDTH * level)


def _fill(
    parts: Sequence[str],
    separator: str,
    first_prefix: str,
    continuation_prefix: str,
    start_column: int = 0,
) -> list[str]:
    """Greedily fill parts onto lines, the first after ``first_prefix`` and later ones after ``continuation_prefix``.

    The first line is measured from ``start_column``, the column the clause starts at,
    because the clause head is positioned by the statement join above it. Continuation
    lines carry their own indentation inside the prefix, so they are measured from
    column 0. A wrapped line keeps the separator's trailing character, so a comma list
    wraps after a comma. The first part always lands on the first line: an expression
    cannot break internally, so a part longer than the width overflows rather than wraps.
    """
    lines: list[str] = []
    current = first_prefix
    limit = WIDTH - start_column
    empty = True
    for part in parts:
        proposed = current + ("" if empty else separator) + part
        if not empty and len(proposed) > limit:
            lines.append(current + separator.rstrip())
            current = continuation_prefix + part
            limit = WIDTH
        else:
            current = proposed
            empty = False
    lines.append(current)
    return lines


@dataclass(frozen=True, weakref_slot=True, slots=True)
class PrettyOccurrence(Layout):
    """The pretty layout for one occurrence: its break mode and indent level."""

    broken: bool
    level: int

    def tokens(self, *parts: str) -> str:
        """Join the tokens of one construct with spaces. Never breaks."""
        return " ".join(parts)

    def series(self, parts: Iterable[str]) -> str:
        """Join the items of a comma-separated list inside one expression. Never breaks."""
        return ", ".join(parts)

    def listed(self, head: str, parts: Iterable[str]) -> str:
        """Join a clause head and its items, wrapping at commas when the clause overflows."""
        items = list(parts)
        flat = f"{head} {', '.join(items)}"
        if self.level * INDENT_WIDTH + len(flat) <= WIDTH:
            return flat
        lines = _fill(items, ", ", f"{head} ", _pad(self.level + 1), start_column=self.level * INDENT_WIDTH)
        return "\n".join(lines)

    def parenthesized(self, keyword: str, parts: Iterable[str]) -> str:
        """Join a keyword and a parenthesized list, wrapping inside the parentheses."""
        items = list(parts)
        flat = f"{keyword} ({', '.join(items)})"
        if self.level * INDENT_WIDTH + len(flat) <= WIDTH:
            return flat
        # The closing parenthesis is appended after the fill measures the last line, so a last item
        # that exactly fills the width renders one column over; a line that cannot break further may exceed the width.
        lines = _fill(items, ", ", f"{keyword} (", _pad(self.level + 1), start_column=self.level * INDENT_WIDTH)
        return "\n".join(lines) + ")"

    def owned(self, text: str, *parts: str) -> str:
        """Append owned sub-clauses, each on its own line one level below the clause."""
        if not parts:
            return text
        if self.broken:
            pad = _pad(self.level + 1)
            return text + "".join(f"\n{pad}{part}" for part in parts)
        return " ".join((text, *parts))

    def packed(self, text: str, *parts: str) -> str:
        """Append owned modifier segments, packed onto one line one level below the clause."""
        if not parts:
            return text
        if self.broken:
            lines = _fill(list(parts), " ", _pad(self.level + 1), _pad(self.level + 1))
            return text + "\n" + "\n".join(lines)
        return " ".join((text, *parts))

    def clauses(self, parts: Iterable[str]) -> str:
        """Join the clauses of one statement, one clause per line when broken."""
        items = list(parts)
        if self.broken:
            return ("\n" + _pad(self.level)).join(items)
        return " ".join(items)

    def between(self, parts: Iterable[str], keyword: str) -> str:
        """Join union branches, the keyword on its own line when broken."""
        items = list(parts)
        if self.broken:
            pad = _pad(self.level)
            return f"\n{pad}{keyword}\n{pad}".join(items)
        return f" {keyword} ".join(items)

    def body(self, header: str, inner: str) -> str:
        """Join a subquery header (``CALL`` or ``EXISTS``), its body one level deeper and the closing brace."""
        return f"{header} {{\n{_pad(self.level + 1)}{inner}\n{_pad(self.level)}}}"


def _holds_subquery(finalised: Statement | UnionStatement) -> bool:
    """
    Return whether a render holds a subquery body.

    A body's braces always break, so a statement holding one breaks around its clauses
    even when the whole render fits on one line. A union is checked branch by branch.
    """
    statements = finalised.parts if isinstance(finalised, UnionStatement) else (finalised,)
    return any(_holds_body(statement) for statement in statements)


def _holds_body(statement: Statement) -> bool:
    """Return whether a statement holds a subquery call clause or an ``EXISTS`` expression."""
    return any(isinstance(clause, SubqueryCallClause) or _holds_exists(clause) for clause in statement.clauses)


def _holds_exists(node: AstNode) -> bool:
    """Return whether a subtree holds an ``ExistsExpression``."""
    return isinstance(node, ExistsExpression) or any(_holds_exists(child) for child in node.children())


class _WalkFrame:
    """One node being visited, its occurrence path and what its children inherit."""

    __slots__ = ("children_broken", "children_level", "next_child_index", "path")

    def __init__(self, path: OccurrencePath, children_broken: bool, children_level: int) -> None:
        self.path = path
        self.children_broken = children_broken
        self.children_level = children_level
        self.next_child_index = 0


class _DecisionWalk(_Visitor):
    """Assign every breakable occurrence its break mode and indent level, top-down."""

    __slots__ = ("__weakref__", "_flat", "_frames", "_table")

    def __init__(self, flat: Mapping[OccurrencePath, int]) -> None:
        """Store the measured flat lengths and prepare an empty table."""
        self._flat = flat
        self._frames: list[_WalkFrame] = []
        self._table: dict[OccurrencePath, PrettyOccurrence] = {}

    def enter(self, node: AstNode) -> None:
        """Derive one occurrence's settings from its container's, then push what its children inherit."""
        if self._frames:
            parent = self._frames[-1]
            path = (*parent.path, parent.next_child_index)
            parent.next_child_index += 1
            inherited_broken, level = parent.children_broken, parent.children_level
        else:
            path, inherited_broken, level = (), False, 0
        if isinstance(node, (Statement, UnionStatement)):
            broken = inherited_broken or self._flat.get(path, 0) + level * INDENT_WIDTH > WIDTH or _holds_subquery(node)
            self._table[path] = PrettyOccurrence(broken, level)
            self._frames.append(_WalkFrame(path, broken, level))
        # Dispatching SubqueryCallClause before the generic Clause branch is policy, not
        # convenience: a call is a clause that must not inherit the plain-clause settings.
        # Both kinds of subquery body always break their braces and start their own break
        # decision one level deeper.
        elif isinstance(node, (SubqueryCallClause, ExistsExpression)):
            self._table[path] = PrettyOccurrence(True, level)
            self._frames.append(_WalkFrame(path, False, level + 1))
        elif isinstance(node, (MergeAction, Where)):
            # An owned part sits one level below its owner when the clause breaks, so a
            # subquery body inside it indents from that printed position.
            settings = PrettyOccurrence(inherited_broken, level + 1)
            self._table[path] = settings
            self._frames.append(_WalkFrame(path, settings.broken, settings.level))
        elif isinstance(node, Clause):
            settings = PrettyOccurrence(inherited_broken, level)
            self._table[path] = settings
            self._frames.append(_WalkFrame(path, settings.broken, settings.level))
        else:
            self._frames.append(_WalkFrame(path, inherited_broken, level))

    def leave(self, node: AstNode) -> None:
        """Pop the frame of the node the walk is leaving."""
        self._frames.pop()


def decide(root: AstNode, flat: Mapping[OccurrencePath, int]) -> Mapping[OccurrencePath, Layout]:
    """Return the pretty layout each breakable occurrence composes through."""
    walk = _DecisionWalk(flat)
    root.accept(walk)
    return walk._table


def render_pretty(
    finalised: Statement | UnionStatement,
    analysis: Analysis,
    always_escape_names: bool,
    rules: RenderingRules,
) -> str:
    """Render one statement or union as multi-line text: measure, decide, compose."""
    captures: dict[OccurrencePath, str] = {}
    measured = RenderingTraversal(rules, analysis, always_escape_names, COMPACT, captures=captures)
    root_text = measured.render(finalised)
    if len(root_text) <= WIDTH and not _holds_subquery(finalised):
        return root_text
    flat = {path: len(text) for path, text in captures.items()}
    occurrences = decide(finalised, flat)
    composed = RenderingTraversal(rules, analysis, always_escape_names, occurrences=occurrences)
    return composed.render(finalised)


__all__ = ["WIDTH", "PrettyOccurrence", "decide", "render_pretty"]

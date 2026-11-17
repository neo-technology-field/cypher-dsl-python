"""Sphinx configuration for the cypher-dsl documentation.

The build is offline. No inventory is downloaded, no example is executed and no
database connection is opened, so the same configuration works in CI and on a machine
without network access.

The published site contains the user documentation only. The contributor pages under
``contributor/`` and the records under ``adr/`` are repository documentation and are
excluded from the build. The API reference documents the ``cypher_dsl`` facade plus
``cypher_dsl.errors``, whose exception types callers import directly, through AutoAPI
directives; the remaining modules implement those names and are parsed without being
rendered as separate pages.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import docutils.nodes as dn
import sphinx.addnodes as an
from pygments.lexers import CypherLexer
from pygments.token import Name, Operator
from sphinx.highlighting import lexers

if TYPE_CHECKING:
    from sphinx.application import Sphinx


class ParameterCypherLexer(CypherLexer):
    """
    The Cypher lexer with query parameters and the operators Pygments omits.

    Pygments rejects ``$name`` and ``$``quoted name`` tokens, and every rendered statement
    in this documentation carries parameters. Its rule set also has no operator token for
    ``+ - * / % ^ ~``, so arithmetic and the regex match operator render as error tokens.
    Both are added here so highlighting succeeds instead of falling back to relaxed mode.
    """

    tokens: ClassVar[dict[str, list[tuple[str, Any]]]] = {
        **CypherLexer.tokens,
        "root": [
            (r"\$(?:[A-Za-z_][A-Za-z0-9_]*|`[^`]+`)", Name.Variable),
            (r"[+\-*/%^~]", Operator),
            *CypherLexer.tokens["root"],
        ],
    }


lexers["cypher"] = ParameterCypherLexer()

project = "cypher-dsl"
author = "Bert Radke"
copyright = "2026, Bert Radke"
language = "en"

extensions = [
    "sphinx.ext.autodoc",
    "autoapi.extension",
    "sphinx.ext.napoleon",
]

autoapi_type = "python"
autoapi_dirs = ["../src/cypher_dsl"]
autoapi_generate_api_docs = False

napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_use_rtype = False
# The facade classes document their fields in Google-style ``Attributes:`` sections. As
# ``:ivar:`` fields those descriptions create no domain objects, so they do not collide
# with the attribute entries the AutoAPI directive registers from the class fields.
napoleon_use_ivar = True

exclude_patterns = ["_build", "contributor", "adr"]

html_theme = "alabaster"
html_title = "cypher-dsl"
html_static_path = ["_static"]
html_css_files = ["docs.css"]

# Files served from the site root for LLM consumption. llms.txt is curated by hand, and
# llms-full.txt is written into the output directory by the hook below.
html_extra_path = ["llms.txt"]

# Pages whose source is directives rather than documentation. The corpus takes their
# rendered text instead of their source.
_DOCTREE_PAGES = frozenset({"api"})

# Nodes that carry cross-reference machinery or internal bookkeeping rather than
# documentation text.
_SKIPPED_NODES = (an.index, an.toctree, dn.comment, dn.system_message, dn.substitution_definition, dn.target)


def _page_source(source: Path, docname: str) -> str | None:
    """Return the source text of a hand-written page, or ``None`` for a generated one.

    Args:
        source: The documentation source directory.
        docname: Document name relative to the source directory, with ``/`` separators.

    Returns:
        The page's reStructuredText or Markdown source, or ``None`` when the document has
        no source file because AutoAPI generated it.
    """
    for suffix in (".rst", ".md"):
        candidate = source / f"{docname}{suffix}"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    return None


def _public_documents(app: Sphinx) -> list[str]:
    """Return every published document in toctree order, starting with the index.

    Args:
        app: The Sphinx application, used for its environment.

    Returns:
        Document names depth-first in reading order. Contributor pages are not in the
        published toctree, so they cannot appear here.
    """
    includes = app.env.toctree_includes
    order: list[str] = ["index"]

    def visit(docname: str) -> None:
        if docname in order:
            return
        order.append(docname)
        for child in includes.get(docname, ()):
            visit(child)

    for child in includes.get("index", ()):
        visit(child)
    return order


def _write_list(node: dn.bullet_list | dn.enumerated_list, marker: str, lines: list[str], indent: str) -> None:
    """Write a bullet or enumerated list, keeping nested lists indented under their item.

    Args:
        node: The list node.
        marker: Prefix rendered before each item.
        lines: Output lines, appended in place.
        indent: Leading spaces for this list level.
    """
    for item in node.children:
        if not isinstance(item, dn.list_item):
            continue
        nested: list[dn.bullet_list | dn.enumerated_list] = []
        texts: list[str] = []
        for child in item.children:
            if isinstance(child, (dn.bullet_list, dn.enumerated_list)):
                nested.append(child)
            else:
                text = child.astext().strip()
                if text:
                    texts.append(" ".join(text.split()))
        lines.append(f"{indent}{marker} {' '.join(texts)}".rstrip())
        for child in nested:
            _write_list(child, "-" if isinstance(child, dn.bullet_list) else "1.", lines, f"{indent}  ")


def _write_table(node: dn.table, lines: list[str]) -> None:
    """Write a table as GitHub-flavoured Markdown pipe rows.

    Args:
        node: The table node.
        lines: Output lines, appended in place.
    """
    rows = [
        [" ".join(cell.astext().split()) for cell in row.findall(dn.entry)]
        for row in node.findall(dn.row)
        if isinstance(row, dn.row)
    ]
    if not rows:
        return
    lines.append("| " + " | ".join(rows[0]) + " |")
    lines.append("| " + " | ".join(["---"] * len(rows[0])) + " |")
    lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
    lines.append("")


def _write_nodes(nodes: list[dn.Node], lines: list[str], depth: int) -> None:
    """Convert doctree nodes to plain text with Markdown-style structure.

    Known block nodes keep their shape: sections become headings, literal blocks become
    fenced code, lists and tables keep their rows. Inline markup loses its formatting,
    because the text is the content that matters. Unknown block nodes fall back to their
    text, so no documentation content is dropped.

    Args:
        nodes: Nodes to convert, siblings in document order.
        lines: Output lines, appended in place.
        depth: Section nesting level, one per enclosing section.
    """
    for node in nodes:
        if isinstance(node, dn.section):
            title = node.next_node(dn.title)
            if title is not None:
                lines.extend((f"{'#' * min(depth + 1, 6)} {title.astext()}", ""))
            _write_nodes([child for child in node.children if not isinstance(child, dn.title)], lines, depth + 1)
        elif isinstance(node, dn.title):
            lines.extend((f"{'#' * min(depth + 1, 6)} {node.astext()}", ""))
        elif isinstance(node, dn.paragraph):
            lines.extend((" ".join(node.astext().split()), ""))
        elif isinstance(node, dn.literal_block):
            lines.extend((f"```{node.get('language', '')}", node.astext().rstrip(), "```", ""))
        elif isinstance(node, dn.bullet_list):
            _write_list(node, "-", lines, "")
            lines.append("")
        elif isinstance(node, dn.enumerated_list):
            _write_list(node, "1.", lines, "")
            lines.append("")
        elif isinstance(node, dn.field_list):
            for field in node.children:
                if not isinstance(field, dn.field):
                    continue
                name_node = field.next_node(dn.field_name)
                body_node = field.next_node(dn.field_body)
                if name_node is not None:
                    lines.append(f"**{name_node.astext()}**")
                if body_node is not None:
                    _write_nodes(list(body_node.children), lines, depth)
                lines.append("")
        elif isinstance(node, dn.definition_list):
            for item in node.children:
                if not isinstance(item, dn.definition_list_item):
                    continue
                term = item.next_node(dn.term)
                definition = item.next_node(dn.definition)
                if term is not None:
                    lines.append(f"**{term.astext()}**")
                if definition is not None:
                    _write_nodes(list(definition.children), lines, depth)
                lines.append("")
        elif isinstance(node, an.desc):
            for signature in node.findall(an.desc_signature):
                text = " ".join(signature.astext().split())
                if text:
                    lines.append(f"    {text}")
            content = node.next_node(an.desc_content)
            if content is not None:
                _write_nodes(list(content.children), lines, depth)
        elif isinstance(node, dn.rubric):
            lines.extend((f"**{node.astext()}**", ""))
        elif isinstance(node, dn.table):
            _write_table(node, lines)
        elif isinstance(node, _SKIPPED_NODES) or node.__class__.__name__ == "pending_xref":
            continue
        else:
            text = node.astext().strip()
            if text:
                lines.extend((text, ""))


def _generated_page_text(app: Sphinx, docname: str) -> str:
    """Return the rendered text of an AutoAPI page.

    Args:
        app: The Sphinx application, used for its environment and doctree directory.
        docname: Generated document name, such as ``autoapi/cypher_dsl/index``.

    Returns:
        The page's documentation as plain text, or an empty string when its doctree was
        not written, which happens on partial builds.
    """
    doctree_path = Path(app.doctreedir) / f"{docname}.doctree"
    if not doctree_path.is_file():
        return ""
    doctree = app.env.get_doctree(docname)
    lines: list[str] = []
    _write_nodes(list(doctree.children), lines, 0)
    return "\n".join(lines).strip()


def _page_text(app: Sphinx, docname: str) -> str:
    """Return the text of one published document.

    Hand-written pages contribute their source, which keeps code examples intact. The
    API page and generated pages contribute their rendered text, because their source is
    directives rather than documentation.

    Args:
        app: The Sphinx application.
        docname: Document name relative to the source directory.

    Returns:
        The document's text in the corpus.
    """
    if docname in _DOCTREE_PAGES:
        return _generated_page_text(app, docname)
    source = _page_source(Path(app.srcdir), docname)
    return source if source is not None else _generated_page_text(app, docname)


def _write_llms_full(app: Sphinx, exception: Exception | None) -> None:
    """Write the published documentation as one file for LLM consumption.

    The corpus is derived from the published toctree, so it contains exactly the pages a
    visitor sees and no contributor page. The file lands in the build output so the
    source tree stays free of generated files, and a failed build writes nothing rather
    than leaving a partial corpus behind.

    Args:
        app: The Sphinx application, used for its source and output directories.
        exception: The build failure, if there is one.
    """
    if exception is not None:
        return
    parts = ["# cypher-dsl documentation"]
    parts.extend(_page_text(app, docname).strip() for docname in _public_documents(app))
    (Path(app.outdir) / "llms-full.txt").write_text("\n\n".join(parts), encoding="utf-8")


def setup(app: Sphinx) -> dict[str, object]:
    """Write the LLM corpus after every successful build."""
    app.connect("build-finished", _write_llms_full)
    return {"parallel_read_safe": True, "parallel_write_safe": True}

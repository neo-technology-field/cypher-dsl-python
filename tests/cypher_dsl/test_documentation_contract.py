"""
Contract checks for the documentation sources.

Every check reads the Markdown and reStructuredText files directly, so a missing record,
an unindexed page or an example that opens a driver fails in an ordinary unit run. The
complete Sphinx build stays a final-gate job, and none of these checks needs Sphinx, a
driver or a database.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS = PROJECT_ROOT / "docs"
ADR_DIR = DOCS / "adr"

TASK_ADRS = {
    "0001-record-architecture-decisions.md": "Task 1",
    "0002-port-vocabulary-not-java-api.md": "Task 2",
    "0003-separate-dialect-language-and-server-target.md": "Task 4",
    "0004-reuse-syntax-through-visitors.md": "Task 3",
    "0005-inline-literals-and-explicit-parameters.md": "Task 4",
    "0006-keep-runtime-independent-of-drivers.md": "Task 1",
    "0007-support-upstream-maintained-python.md": "Task 1",
}

ADR_FIELDS = ("## Context", "## Decision", "## Consequences", "## Alternatives considered")

DOCUMENTED_PAGES = (
    "getting-started",
    "parameters",
    "dialects",
    "architecture",
    "testing",
    "adr/index",
)

DRIVER_TOKENS = (
    "import neo4j",
    "from neo4j",
    "neo4j.",
    "testcontainers",
    "GraphDatabase",
    "execute_query",
    ".run(",
    "session.",
)

LLMS_LINK = re.compile(r"\]\(([^)]+)\)")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _page_path(page: str) -> Path:
    for suffix in (".rst", ".md"):
        path = DOCS / f"{page}{suffix}"
        if path.is_file():
            return path
    raise FileNotFoundError(f"Documentation page {page!r} is listed but missing.")


def _prose(text: str) -> str:
    """Collapse whitespace so a phrase check does not depend on line wrapping."""
    return " ".join(text.split())


def _toctree_entries(text: str) -> list[str]:
    entries: list[str] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip() != ".. toctree::":
            index += 1
            continue
        directive_indent = len(line) - len(line.lstrip())
        index += 1
        while index < len(lines):
            entry_line = lines[index]
            if not entry_line.strip():
                index += 1
                continue
            if len(entry_line) - len(entry_line.lstrip()) <= directive_indent:
                break
            entry = entry_line.strip()
            if not entry.startswith(":"):
                entries.append(entry)
            index += 1
    return entries


def _code_blocks(path: Path, language: str = "python") -> list[str]:
    marker = f".. code-block:: {language}"
    lines = _read(path).splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip() != marker:
            index += 1
            continue
        directive_indent = len(line) - len(line.lstrip())
        index += 1
        body: list[str] = []
        while index < len(lines):
            body_line = lines[index]
            if not body_line.strip():
                body.append("")
                index += 1
                continue
            if len(body_line) - len(body_line.lstrip()) <= directive_indent:
                break
            body.append(body_line)
            index += 1
        while body and not body[-1].strip():
            body.pop()
        indents = [len(body_line) - len(body_line.lstrip()) for body_line in body if body_line.strip()]
        margin = min(indents) if indents else 0
        blocks.append("\n".join(body_line[margin:] for body_line in body))
    return blocks


def _documented_sources() -> list[Path]:
    return sorted(path for path in DOCS.rglob("*.rst") if "_build" not in path.parts and "_generated" not in path.parts)


def _conf_values() -> dict[str, object]:
    """Read the literal module-level assignments from the Sphinx configuration."""
    values: dict[str, object] = {}
    for node in ast.parse(_read(DOCS / "conf.py")).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            values[target.id] = ast.literal_eval(node.value)
        except ValueError:
            continue
    return values


def _conf_namespace() -> dict[str, object]:
    """Execute the Sphinx configuration so its hooks can be called directly."""
    source = DOCS / "conf.py"
    namespace: dict[str, object] = {"__file__": str(source), "__name__": "cypher_dsl_docs_conf"}
    exec(compile(_read(source), str(source), "exec"), namespace)
    return namespace


@pytest.mark.parametrize(("adr_name", "owner"), sorted(TASK_ADRS.items()))
def test_every_planned_adr_exists_with_the_required_shape(adr_name: str, owner: str) -> None:
    path = ADR_DIR / adr_name
    assert path.is_file(), f"{adr_name} is missing. {owner} owns this record."

    text = _read(path)
    number = adr_name.split("-")[0]
    assert text.splitlines()[0].startswith(f"# {number}: "), f"{adr_name} must start with '# {number}: <title>'."
    assert "- Status: accepted." in text, f"{adr_name} must record an accepted status."

    positions = [text.find(field) for field in ADR_FIELDS]
    assert all(position >= 0 for position in positions), f"{adr_name} is missing one of {ADR_FIELDS}."
    assert positions == sorted(positions), f"{adr_name} must keep the record fields in order."
    assert not re.search(r"\b(TODO|TBD)\b", text), f"{adr_name} still contains an unresolved placeholder."


def test_adr_index_lists_every_record_once() -> None:
    entries = _toctree_entries(_read(ADR_DIR / "index.rst"))
    expected = [Path(name).stem for name in sorted(TASK_ADRS)]
    assert entries == expected

    for entry in entries:
        assert (ADR_DIR / f"{entry}.md").is_file(), f"{entry} is indexed but missing."


def test_adr_template_records_the_same_fields() -> None:
    text = _read(ADR_DIR / "template.md")
    assert text.splitlines()[0].startswith("# NNNN: ")
    assert "- Status: " in text
    for field in ADR_FIELDS:
        assert field in text


def test_documented_pages_exist_and_are_indexed() -> None:
    entries = _toctree_entries(_read(DOCS / "index.rst"))
    for page in DOCUMENTED_PAGES:
        _page_path(page)
        assert page in entries, f"{page} is not reachable from index.rst."
    for entry in entries:
        _page_path(entry)


def test_architecture_page_is_indexed_included_and_packaged() -> None:
    architecture = PROJECT_ROOT / "doc" / "ARCHITECTURE.md"
    assert architecture.is_file()
    source = architecture.read_text(encoding="utf-8")
    wrapper = (DOCS / "architecture.md").read_text(encoding="utf-8")
    index = _read(DOCS / "index.rst")
    pyproject = _read(PROJECT_ROOT / "pyproject.toml")
    readme = _read(PROJECT_ROOT / "README.md")
    assert "[Architecture](doc/ARCHITECTURE.md)" in readme
    assert "architecture" in _toctree_entries(index)
    assert "{include}" in wrapper and "../doc/ARCHITECTURE.md" in wrapper
    assert "doc/ARCHITECTURE.md" in pyproject
    for phrase in (
        "traversal",
        "analysis",
        "dialect definition",
        "occurrence path",
        "BindingCollector",
        "legacy ElementId",
        "server/version policy",
    ):
        assert phrase in source


def test_python_examples_compile_and_never_open_a_driver() -> None:
    for path in _documented_sources():
        for block in _code_blocks(path):
            compile(block, str(path), "exec")
            leaked = [token for token in DRIVER_TOKENS if token in block]
            assert not leaked, f"{path} example mentions {leaked}; documentation examples must not open a driver."


def test_query_examples_parameterise_request_data() -> None:
    for path in _documented_sources():
        for block in _code_blocks(path):
            if ".where(" in block:
                assert "param(" in block, f"{path} filters on data without param(); request data belongs in a binding."

    parameters = _read(DOCS / "parameters.rst")
    assert "request data" in parameters
    assert 'param("min_rating")' in parameters, "The unbound form must be documented."
    assert 'param("min_rating", 4.5)' in parameters, "The bound form must be documented."


def test_dialect_page_covers_the_public_enumeration() -> None:
    text = _read(DOCS / "dialects.rst")
    for member in Dialect:
        assert member.name in text, f"{member.name} is not documented."
    assert "server_version" in text
    assert "always_escape_names" in text
    assert "pretty_print=True" in text


def test_sphinx_configuration_stays_offline() -> None:
    values = _conf_values()

    extensions = values["extensions"]
    assert isinstance(extensions, list)
    assert {"autoapi.extension", "sphinx.ext.napoleon", "myst_parser"} <= set(extensions)
    assert "sphinx.ext.intersphinx" not in extensions
    assert values["autoapi_type"] == "python"
    assert values["autoapi_dirs"] == ["../src/cypher_dsl"]
    exclude_patterns = values["exclude_patterns"]
    assert isinstance(exclude_patterns, list)
    assert "adr/template.md" in exclude_patterns, "The record template must not become a built document."


def test_llms_page_list_matches_the_documented_pages() -> None:
    pages = _conf_values()["llms_pages"]
    assert isinstance(pages, tuple)
    entries = [entry for entry in _toctree_entries(_read(DOCS / "index.rst")) if entry != "adr/index"]
    assert list(pages) == ["index", *entries], "llms_pages must list the documented pages in reading order."
    for page in pages:
        _page_path(page)


def test_llms_index_links_point_at_built_pages() -> None:
    text = _read(DOCS / "llms.txt")
    pages = _conf_values()["llms_pages"]
    assert isinstance(pages, tuple)
    targets = LLMS_LINK.findall(text)
    assert targets, "docs/llms.txt must link to the documentation."

    generated = {"llms-full.txt", "autoapi/cypher_dsl/index.html"}
    for target in targets:
        assert not target.startswith(("http://", "https://")), f"{target} must stay relative."
        if target in generated:
            continue
        assert target.endswith(".html"), f"{target} is not a page of the built site."
        assert target.removesuffix(".html") in pages, f"{target} names a page that llms-full.txt does not carry."

    for page in pages:
        if page == "index":
            continue
        assert f"]({page}.html)" in text, f"docs/llms.txt must link to {page}.html."


def test_llms_corpus_is_written_to_the_output_directory(tmp_path: Path) -> None:
    write_corpus = _conf_namespace()["_write_llms_full"]
    assert callable(write_corpus)
    pages = _conf_values()["llms_pages"]
    assert isinstance(pages, tuple)

    write_corpus(SimpleNamespace(srcdir=str(DOCS), outdir=str(tmp_path)), None)

    corpus = (tmp_path / "llms-full.txt").read_text(encoding="utf-8")
    assert corpus.startswith("# cypher-dsl documentation")
    positions = [corpus.index(_read(_page_path(page)).splitlines()[0].strip()) for page in pages]
    assert positions == sorted(positions), "The corpus must keep the pages in reading order."
    assert "one more AST pass and storage for occurrence metadata" in _prose(corpus)


def test_llms_corpus_is_skipped_after_a_failed_build(tmp_path: Path) -> None:
    write_corpus = _conf_namespace()["_write_llms_full"]
    assert callable(write_corpus)

    write_corpus(SimpleNamespace(srcdir=str(DOCS), outdir=str(tmp_path)), RuntimeError("build failed"))

    assert not (tmp_path / "llms-full.txt").exists(), "A failed build must not leave a partial corpus behind."


def test_rendered_bindings_are_isolated_without_rebinding() -> None:
    from cypher_dsl import Configuration, Renderer, match, node, param

    for path in (DOCS / "index.rst", DOCS / "getting-started.rst", PROJECT_ROOT / "README.md"):
        text = _prose(_read(path))
        assert "holds no bindings" not in text, f"{path} denies that bound occurrences live in the tree."
        assert "carries no bindings" not in text, f"{path} denies that bound occurrences live in the tree."
        assert "binding bag" in text, f"{path} must name the absent statement-level binding bag."
        assert "execution layer" in text, f"{path} must say who supplies values for an unbound template."
        assert "unbound" in text, f"{path} must distinguish reuse of an unbound template from rebinding."

    person = node("Person", name="p")
    query = match(person).where(person["year"] == param("year", 2000)).returning(person)
    renderer = Renderer.get(Configuration(server_version="5.26"))
    first = renderer.render(query)
    first.parameters["year"] = 2020
    assert renderer.render(query).parameters == {"year": 2000}, "Fresh containers must not rebind the tree."


def test_raw_text_is_trusted_and_not_contained() -> None:
    text = _prose(_read(DOCS / "getting-started.rst"))
    assert "cannot smuggle" not in text, "An expression-only API is not a containment guarantee."
    assert "trusted" in text
    assert "bypasses" in text
    assert "not a parser or security guarantee" in text


def test_name_slot_example_projects_an_introduced_name() -> None:
    from cypher_dsl import Configuration, Renderer, lit, match, node

    text = _read(DOCS / "parameters.rst")
    assert 'returning("p", lit("p"))' in text, "The name-slot example must project a name the pattern introduced."
    assert "MATCH (p:Person) RETURN p, 'p'" in text
    assert "those positions cannot name a variable" not in text, "Variable expressions remain supported there."
    assert 'name("p")' in text

    person = node("Person", name="p")
    rendered = Renderer.get(Configuration(server_version="5.26")).render(match(person).returning("p", lit("p")))
    assert rendered.cypher == "MATCH (p:Person) RETURN p, 'p'"


def test_parameter_name_quoting_is_documented_accurately() -> None:
    from cypher_dsl import Configuration, Renderer, match, node, param

    text = _read(DOCS / "parameters.rst")
    assert "Parameter names are not quoted" not in text, "Only the keyword exception is waived after $."
    assert 'param("request value", 1)' in text
    assert "$`request value`" in text
    assert "always_escape_names=True" in text
    assert "$`value`" in text

    person = node("Person", name="p")
    default = Renderer.get(Configuration(server_version="5.26")).render(
        match(person).returning(param("request value", 1))
    )
    assert default.cypher == "MATCH (p:Person) RETURN $`request value`"
    forced = Renderer.get(Configuration(server_version="5.26", always_escape_names=True)).render(
        match(person).returning(param("value", 1))
    )
    assert forced.cypher == "MATCH (`p`:`Person`) RETURN $`value`"


def test_lit_accepts_python_values_and_not_expressions() -> None:
    from cypher_dsl import Configuration, Renderer, fn, lit, match, node
    from cypher_dsl.errors import InvalidLiteralError

    text = _prose(_read(DOCS / "parameters.rst"))
    assert "comparisons and ``lit()``" not in text, "lit() does not accept expressions like comparisons do."
    assert "``lit()`` is different" in text
    assert "Python literal values only" in text
    assert "InvalidLiteralError" in text
    assert "Bind such a value with ``param()``" not in text, "An expression is passed to the API, not bound as data."

    person = node("Person", name="p")
    variable = person.as_expression()
    rendered = Renderer.get(Configuration(server_version="5.26")).render(
        match(person).returning(fn("coalesce", variable))
    )
    assert rendered.cypher == "MATCH (p:Person) RETURN coalesce(p)"
    with pytest.raises(InvalidLiteralError):
        lit(variable)


def test_dialect_profile_notes_are_not_feature_claims() -> None:
    text = _prose(_read(DOCS / "dialects.rst"))
    assert "Adds the newer importing" not in text
    assert "Adds dynamic labels" not in text
    assert "profile flags" in text.lower()
    assert "reserved" in text.lower()
    assert "not public construction features" in text


def test_typing_consumer_documents_the_static_runtime_boundary() -> None:
    text = _prose(_read(PROJECT_ROOT / "tests" / "typing" / "public_api.py"))
    assert "static" in text
    assert "no-ops at run time" in text

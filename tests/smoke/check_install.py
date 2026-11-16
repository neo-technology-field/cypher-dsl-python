"""
Check an installed cypher-dsl distribution outside the repository checkout.

Run with ``python -I`` from a directory other than the project, so the import resolves to
the installed distribution rather than to ``src/``. The script uses the standard library
only, checks the public facade and a parameterised render, and reports the first failed
expectation. That keeps it usable in the wheel build session, where no test dependency is
installed.
"""

import sys
from importlib.metadata import PackageNotFoundError, metadata
from pathlib import Path

EXPECTED_CYPHER = "MATCH (m:Movie) WHERE m.released < $year RETURN m.title"
EXPECTED_PARAMETERS = {"year": 2000}
FORBIDDEN_MODULES = ("neo4j", "testcontainers")


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def main() -> int:
    """Return zero when the installed distribution is complete, one otherwise."""
    try:
        distribution = metadata("cypher-dsl")
    except PackageNotFoundError:
        return _fail("cypher-dsl is not installed in this interpreter")

    requirements = distribution.get_all("Requires-Dist", [])
    if requirements:
        return _fail(f"unexpected runtime requirements: {requirements}")

    try:
        import cypher_dsl
    except ImportError as error:
        return _fail(f"the installed package does not import: {error}")

    marker = Path(cypher_dsl.__file__).with_name("py.typed")
    if not marker.is_file():
        return _fail(f"missing typing marker: {marker}")

    exported = getattr(cypher_dsl, "__all__", [])
    if not exported:
        return _fail("the public facade exports nothing")
    missing = [name for name in exported if not hasattr(cypher_dsl, name)]
    if missing:
        return _fail(f"the public facade is missing exported names: {missing}")

    from cypher_dsl import Configuration, Renderer, match, node, param

    movie = node("Movie", name="m")
    query = match(movie).where(movie["released"] < param("year", 2000)).returning(movie["title"])
    rendered = Renderer.get(Configuration(server_version="5.26")).render(query)

    if rendered.cypher != EXPECTED_CYPHER:
        return _fail(f"unexpected rendering: {rendered.cypher!r}")
    if rendered.parameters != EXPECTED_PARAMETERS:
        return _fail(f"unexpected parameters: {rendered.parameters!r}")
    if rendered.unbound_parameters:
        return _fail(f"unexpected unbound parameters: {sorted(rendered.unbound_parameters)}")

    leaked = [name for name in FORBIDDEN_MODULES if name in sys.modules]
    if leaked:
        return _fail(f"the library imported test or driver packages: {leaked}")

    print("installed distribution ships py.typed and renders a parameterised query")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

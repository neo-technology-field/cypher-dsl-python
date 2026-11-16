# cypher-dsl-python

Build Cypher queries as Python syntax objects and render them to text plus parameters. The
AST vocabulary and rendering behaviour follow the Java Neo4j
[Cypher-DSL](https://github.com/neo4j/cypher-dsl). This is not an official Neo4j product.

The library covers a read and write subset of Cypher 5. It has no runtime dependencies,
ships `py.typed` and never opens a connection. Drivers, transactions and schema
installation belong to the application or its test harness.

## Documentation

The user guide and API reference are published at
https://neo-technology-field.github.io/cypher-dsl-python/.

## Install

```sh
pip install cypher-dsl
```

In a uv project, use `uv add cypher-dsl`. Python 3.11 to 3.15 are supported.

## Build and render a statement

```python
from cypher_dsl import Configuration, Renderer, match, node, param

movie = node("Movie", name="m")
statement = match(movie).where(movie["released"] < param("year", 2000)).returning(movie["title"])
rendered = Renderer.get(Configuration(server_version="5.26")).render(statement)

print(rendered.cypher)
print(rendered.parameters)
```

```text
MATCH (m:Movie) WHERE m.released < $year RETURN m.title
{'year': 2000}
```

The statement is frozen, and a bound parameter occurrence is part of the tree. It carries
no separate mutable binding bag, and every render returns fresh parameter containers. To
reuse one template with different request values, leave the parameter unbound and supply
the value in your execution layer.

## Bind a value or leave the parameter open

`param(name)` is unbound and `param(name, value)` is bound. Rendering reports what the
caller still has to supply instead of inventing a value:

```python
from cypher_dsl import Configuration, Renderer, match, node, param

person = node("Person", name="p")
statement = match(person).where(person["email"] == param("email")).returning(person["display_name"])
rendered = Renderer.get(Configuration(server_version="5.26")).render(statement)

print(rendered.cypher)
print(rendered.parameters)
print(sorted(rendered.unbound_parameters))
```

```text
MATCH (p:Person) WHERE p.email = $email RETURN p.display_name
{}
['email']
```

A bare string in a projection is a variable name, so a string value needs `lit()`.
Literals are snapshotted at construction, and inline `bytes` is rejected in favour of a
bound parameter.

## Choose a target

- `server_version` is required. Declare the Neo4j release the rendered text will run on, such as
  `Configuration(server_version="5.26")`. Neo4j 5.26 LTS is the minimum. Earlier 5.x releases
  and 4.x are unsupported.
- `Language.AUTO` is the default. It selects a language per statement from the syntax requirements,
  not the newest language the server offers. Statements without a language floor remain unprefixed.
- Pin `Language.CYPHER_5` or `Language.CYPHER_25` when the text must always name its language.
  A `CYPHER 25` pin requires Neo4j 2025.06. Every supported release accepts the `CYPHER 5`
  prefix. Pinning also rejects syntax that requires a different language.
- `Language.NONE` suppresses the prefix but still checks the declared release. The database's
  default language then decides the grammar. A compatible release does not guarantee that its
  configured default can parse the query text.

```python
from cypher_dsl import Configuration, Language

automatic = Configuration(server_version="2026.10")
cypher_5 = Configuration(server_version="2026.10", language=Language.CYPHER_5)
cypher_25 = Configuration(server_version="2026.10", language=Language.CYPHER_25)
database_default = Configuration(server_version="2026.10", language=Language.NONE)
```

The library never probes a server. The declared release is the single source of truth for capability checks.
See [Choose a target](docs/targets.rst) for the floor table and sources.
`pretty_print=True` raises `UnsupportedFeatureError` rather than being ignored.

## What is not available

- No OGM, driver connection, transaction or schema installation.
- No `CALL` subqueries, `SEARCH`, path selectors, quantified path patterns or catalogue
  analysis.
- No pretty printing and no parser.
- No automatic parameter binding.
- No inline bytes literal.
- No complete semantic validator. Clause order, known references and bindings are checked.
  Server-side semantics are not.

## Where this comes from

The vocabulary is not mine. The general architecture, AST names, the rendering and escaping
rules and many of the test scenarios come from the Java
[Cypher-DSL](https://github.com/neo4j/cypher-dsl), which is Apache-2.0. Thanks to the
authors and contributors of that project.

The correspondence was traced against the upstream repository at commit `d3b17e42`, one
commit after the 2025.3.6 release. `NOTICE` lists what was taken from where, and a test
module that ports scenarios names the upstream test file at the top of the module.

This is an independent project. It is not an official Neo4j product, and nothing here is
endorsed or governed by Neo4j, Inc.

## Work on the package

The user documentation is the Sphinx site under `docs/`. Contributor documentation is
repository-only Markdown and is not part of the published site:

- [Architecture](docs/contributor/architecture.md): rendering stages, occurrence analysis, shared rules and target checks.
- [Testing the package](docs/contributor/testing.md): what the unit suite guarantees, and the optional server audit of the rendered corpus.
- [Architecture decisions](docs/adr/index.md): the accepted, superseded and rejected records.

```sh
make deps          # uv sync --group dev --group test
make test          # uv run --group test pytest
make matrix        # every session once on every supported interpreter
make lint
make format-check
make typing
make docs          # Sphinx build
make package       # Nox package session: sdist, wheel, installed smoke test
```

`make help` lists the targets. Unit tests assert rendered text and parameters offline and
need no database. `make cypher-audit` checks a corpus of rendered statements against a
running server when you change a rendering rule.

## Licence

Apache-2.0. See `LICENSE` and `NOTICE`.

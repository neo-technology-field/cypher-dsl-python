# Testing the package

Most of this library is testable without a database. Text, parameters and structure are
values, so the unit suite asserts them directly. Nothing in `src/cypher_dsl` imports a
driver or installs schema.

## What the unit suite guarantees

`pytest` discovers `tests/cypher_dsl` only. Every test asserts the complete rendered
text and the parameter containers of one statement, offline and in milliseconds, so no
Docker and no driver are needed for a unit run.

`tests/cypher_dsl/test_public_surface.py` holds the surface together: every name in
`cypher_dsl.__all__` is accounted for with an expected statement or an expected value.
Adding a public name fails that file until an example exists, and changing a rendering
rule fails it with the text that changed. The expectations are the contract, not a
transcription of current output.

## Check the rendered corpus against a server

The unit suite proves what the text is, not that a server parses it. The audit tool
answers that second question. It records every statement the unit suite renders, sends
each unique statement to a server as `EXPLAIN <statement>` with its parameters, and
reports the statements the server rejects. `EXPLAIN` parses and plans without executing,
so write statements, missing data and an empty database do not matter.

Start a server you own, then run the audit with its credentials:

```sh
docker run --rm -p 7687:7687 -e NEO4J_AUTH=neo4j/audit-password neo4j:2026.10.2-community

make cypher-audit                       # uv run --group audit python -m tools.check_cypher
uv run --group audit python -m tools.check_cypher --password audit-password
```

The tool loads `tools/record_cypher.py` as a pytest plugin, which wraps `Renderer.render`
for the session and keeps each result in memory, so parameter values keep their Python
types. Connection settings come from `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` and
`NEO4J_DATABASE`, with `bolt://localhost:7687`, user `neo4j` and database `neo4j` as
defaults.

Three groups appear in the report:

- Fragments are skipped. The suite deliberately renders clauses such as a lone `SET` or
  `WHERE`, which are valid only inside a statement.
- Unverifiable statements are counted apart. A fragment that parses but names a variable
  the surrounding statement would have bound is rejected for `not defined`, which says
  nothing about the text.
- Rejects are printed with the test that rendered each, up to twenty of them. A reject is
  a question, not a verdict: some tests render invalid text on purpose, such as an unknown
  function name or an escape attempt. A new reject stands out from the baseline. Pass
  `--strict` to turn any reject into a non-zero exit status.

Run the audit when a rendering rule changes. The `audit` dependency group holds the
driver, and it is tooling: neither the unit suite nor the runtime needs it.

## Packaging sessions

`uv run nox -s package` builds an sdist, asserts the contributor documentation is
inside it, builds the wheel from that sdist, installs only the wheel with `--no-deps`, and
runs `tests/smoke/check_install.py` under `python -I` from a temporary directory. The
smoke check asserts an empty `Requires-Dist` and that the installed distribution imports
without the checkout, which catches a missing file in the sdist and an accidental
dependency on the working tree.

## What not to test here

- Do not assert server semantics such as constraint enforcement without a server. `EXPLAIN`
  evidence is parse and plan evidence, not execution evidence.
- Do not treat a rendering assertion as proof that a server accepts the statement.
- Do not point the audit at a database you do not own. It sends statements and credentials
  to that server; a disposable container is cheaper than a shared database.

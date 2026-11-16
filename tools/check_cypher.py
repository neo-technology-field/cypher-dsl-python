"""
Check the statements the test suite renders against a running Neo4j server.

The unit suite asserts rendered text offline. This tool answers the other question: does
that text parse? It records every statement the unit suite renders, sends each one to a
server as ``EXPLAIN <statement>`` with its parameters, and reports the statements the
server rejects. ``EXPLAIN`` parses and plans without executing, so write statements,
missing data and an empty database do not matter.

Start a server first:

    docker run --rm -p 7687:7687 -e NEO4J_AUTH=neo4j/audit-password neo4j:2026.10.2-community

Then, with the credentials the tool expects:

    uv run --group audit python -m tools.check_cypher --password audit-password

Statements that are clauses or fragments rather than complete queries are skipped: a
``SET`` or ``WHERE`` rendered on its own is valid only inside a statement, and the unit
suite renders those deliberately. A reject is a question, not a verdict: some tests render
text that is invalid on purpose, such as an unknown function name or an escape attempt. Each
reject is printed with the test that rendered it, so a new one stands out from the baseline.
Pass ``--strict`` to turn any reject into a non-zero exit status.
"""

from __future__ import annotations

import sys

import click
import pytest
from neo4j import GraphDatabase

import tools.record_cypher as recorder

STATEMENT_STARTERS = frozenset(
    {"MATCH", "CREATE", "MERGE", "UNWIND", "WITH", "RETURN", "CALL", "OPTIONAL", "USE", "CYPHER"}
)
FAILURES_SHOWN = 20


def _collect() -> list[dict[str, object]]:
    """Run the unit suite with the recorder loaded and return what it rendered."""
    recorder.RECORDS.clear()
    exit_code = pytest.main(["-q", "--no-header", "-p", "tools.record_cypher", "--record-cypher", "tests/cypher_dsl"])
    if exit_code != pytest.ExitCode.OK:
        raise click.ClickException("The unit suite did not pass, so there is no corpus worth auditing.")
    return recorder.RECORDS


def _is_statement(cypher: str) -> bool:
    """Return whether the text starts a statement rather than continuing one."""
    words = cypher.split()
    return bool(words) and words[0].upper() in STATEMENT_STARTERS


def _unique(records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Drop repeated statements, keeping the first parameters for each text."""
    seen: set[str] = set()
    unique: list[dict[str, object]] = []
    for record in records:
        cypher = str(record["cypher"])
        if cypher in seen:
            continue
        seen.add(cypher)
        unique.append(record)
    return unique


def _names_an_undefined_variable(message: str) -> bool:
    """
    Return whether the server rejected the text because a variable is not bound.

    The unit suite renders fragments such as ``RETURN elementId(n)`` to assert a text
    shape, and a fragment names variables the surrounding statement would have bound.
    Those statements parse, so they cannot be judged here and are counted apart.
    """
    return "not defined" in message


@click.command()
@click.option("--uri", default="bolt://localhost:7687", show_default=True, envvar="NEO4J_URI")
@click.option("--user", default="neo4j", show_default=True, envvar="NEO4J_USER")
@click.option("--password", required=True, envvar="NEO4J_PASSWORD", help="Password of the audit server.")
@click.option("--database", default="neo4j", show_default=True, envvar="NEO4J_DATABASE")
@click.option("--strict", is_flag=True, default=False, help="Exit with status 1 when the server rejects a statement.")
def main(uri: str, user: str, password: str, database: str, strict: bool) -> None:
    """Send every statement the unit suite renders to a server and report rejects."""
    records = _collect()
    statements = [record for record in _unique(records) if _is_statement(str(record["cypher"]))]
    skipped = len(_unique(records)) - len(statements)

    failures: list[tuple[str, str, str, str]] = []
    unverifiable = 0
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        for record in statements:
            cypher = str(record["cypher"])
            parameters = dict(record["parameters"])  # type: ignore[arg-type]
            parameters.update({name: None for name in record["unbound"]})  # type: ignore[union-attr]
            try:
                driver.execute_query(f"EXPLAIN {cypher}", parameters_=parameters, database_=database)
            except Exception as error:
                message = str(error)
                if _names_an_undefined_variable(message):
                    unverifiable += 1
                    continue
                failures.append((cypher, str(getattr(error, "code", "")), message, str(record.get("test", ""))))
    finally:
        driver.close()

    click.echo(
        f"{len(statements)} statements checked, {skipped} fragments skipped, "
        f"{unverifiable} unverifiable, {len(failures)} rejected."
    )
    for cypher, code, message, test in failures[:FAILURES_SHOWN]:
        first_line = message.splitlines()[0] if message else ""
        click.echo(f"\n{cypher}\n  {code} {first_line}\n  rendered by {test}")
    if len(failures) > FAILURES_SHOWN:
        click.echo(f"\n{len(failures) - FAILURES_SHOWN} further rejects not shown.")
    if failures and strict:
        sys.exit(1)


if __name__ == "__main__":
    main()

# 0006: Keep the runtime independent of drivers

- Status: accepted.

## Context

- The library builds syntax and renders Cypher text plus parameters. It does not need a connection to do
  that.
- A driver dependency would add a version constraint, connection lifecycle and error types to every
  consumer, including projects that use a different driver or no database at all.
- Consumers still need to pass driver-compatible values, such as types the server accepts as parameter
  values, without the library importing the driver.

## Decision

- Keep `dependencies = []` in `pyproject.toml` and assert an empty `Requires-Dist` in the packaging test.
- Keep the Neo4j driver in the `audit` dependency group. It backs the optional corpus audit and is
  tooling, not runtime code. The unit suite and the runtime need no driver and no container.
- Do not import a driver anywhere under `src/cypher_dsl`. Connections, transactions, retries, result
  streaming and schema installation stay outside this project.
- Allow bound parameter values to carry opaque, driver-compatible objects. Such an object remains
  caller-owned, is not inspected or mutated by the library, and the caller must not change it during
  rendering.
- Ship `py.typed` and check the installed distribution with `python -I` from outside the repository, so an
  accidental dependency on the checkout or on an ambient package fails the check.

## Consequences

- Consumers choose their driver and its version independently of this library.
- Capability decisions use the declared server release and language rather than probing a live server.
- Server-side parse evidence comes from the optional audit, run against a server the contributor starts
  and owns. The unit suite never needs Docker or a driver.
- Opaque values can defeat the guarantee of deeply immutable syntax. The documentation has to state the
  caller's obligation rather than weaken the parameter API.
- Wheel contents must stay importable without test or driver packages. That makes the packaging smoke
  script a permanent check, not one-off setup.

## Alternatives considered

- Depend on the Neo4j driver for value types and errors. It would remove the opaque-value caveat, at the
  cost of a driver version in every install and a release cadence this project does not control.
- Publish an optional extra such as `cypher-dsl[neo4j]`. It narrows the default install but still couples
  the documented integration path to one driver and duplicates what the extra would contain.
- Copy the driver's value classes. It duplicates a public API this project does not own and creates
  conversion problems at the parameter boundary.

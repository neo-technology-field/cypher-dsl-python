# 0003: Separate dialect identity, language selection and server target

- Status: accepted.

## Context

- The upstream project exposes eight dialect names. Callers and pinned fixtures select behaviour by name, and some names render identically. `NEO4J_5_26` and `NEO4J_5_CYPHER_5` both render `CYPHER 5`, while `NEO4J_5`, `NEO4J_5_DEFAULT_CYPHER` and `NEO4J_2025` render no prefix.
- A single enum cannot describe a server release. Cypher 25 is not one feature set: vector `SEARCH`, full-text `SEARCH` and dynamic labels arrived in different releases. Treating `NEO4J_5_CYPHER_25` as proof that every Cypher 25 construct is usable overstates what the library knows.
- Enum comments are not the authority for handler behaviour. At the pinned commit `NEO4J_5_DEFAULT_CYPHER.getHandler()` delegates to `NEO4J_5_26`, so the default profile has scope clauses and native dynamic labels. `NEO4J_2025.getHandler()` delegates to `NEO4J_5_23` and keeps `Neo4j5Pre26LabelsVisitor`, so it does not have native dynamic labels. The implementation decides the profile, not the comment above the member.
- Upstream tests pin the language prefix directly, for example `CYPHER 5 EXPLAIN ...` and the no-double-prefix union case. Those are rendering facts, not capability claims.
- The runtime has no driver dependency and must not contact a server to learn its version. A caller who needs a later-release feature has to state the target.

## Decision

- Keep `Dialect` as eight members with unique string values equal to their names. No two members are aliases, so `Dialect.NEO4J_5_26 is not Dialect.NEO4J_5_CYPHER_5` even though their profiles match.
- Keep the rendering profile in a separate table. A `DialectProfile` holds the language prefix, whether scope clauses are rendered, whether dynamic labels are available and whether the member explicitly selects Cypher 25. Derive each profile from the handler that the pinned `Dialect.java` selects, not from the enum comment.
- Treat the upstream default as `NEO4J_5_DEFAULT_CYPHER` with no prefix. It delegates to the 5.26 handler, so it shares that handler's scope-clause and dynamic-label profile while keeping its own identity and prefix. Render `CYPHER 5` only for `NEO4J_5_26` and `NEO4J_5_CYPHER_5`, and `CYPHER 25` only for `NEO4J_5_CYPHER_25`.
- Give `NEO4J_2025` no prefix and the 5.23 handler profile. It renders scope-aware subqueries but keeps the pre-5.26 label visitor, so dynamic labels are not claimed for it.
- Let the profile decide baseline capabilities, then intersect them with the release that introduced them. Scope clauses follow the 5.23 floor and dynamic labels follow the 5.26 floor. A declared older server narrows the baseline rather than being overruled by it.
- Parse a declared `server_version` into integer components in `ServerVersion`. Ordering is numeric, so `5.26` is later than `5.9`. Reject malformed strings when the `Configuration` is built.
- Treat a dialect that names a release as asserting that release as a floor: `NEO4J_5_23` requires 5.23, `NEO4J_5_26` and `NEO4J_5_CYPHER_5` require 5.26, `NEO4J_5_CYPHER_25` requires 2025.06, and `NEO4J_2025` requires 5.23. The default dialect has no floor because it is meant to run under the database's own default, and its individual capabilities still intersect the release minima.
- Validate the dialect and declared server in the `Renderer` constructor, so `Renderer.get` and direct construction cannot diverge. Vector `SEARCH` requires explicit Cypher 25 and a declared server of 2026.01 or later. Full-text `SEARCH` requires explicit Cypher 25 and 2026.09 or later. An undeclared server grants no later-release capability.
- Render the prefix outside traversal of union branches and before any `EXPLAIN` or `PROFILE` word.

## Consequences

- A later-release feature either has a stated server target or is refused. The refusal names the construct, the dialect, the declared target and the supported alternative.
- Adding an upstream dialect member means adding a profile entry, reading its handler and deciding its baseline. Membership and comments alone never grant syntax.
- Equal profiles remain separate identities. A future upstream difference between two names can be expressed without changing the public enum.
- The default dialect now claims scope clauses and dynamic labels, matching its handler. It still renders no prefix, so a server that does not support those constructs fails on the construct, not on the dialect name.
- `NEO4J_2025` stops claiming dynamic labels. A caller who needs them selects a 5.26-based member and declares a compatible server.
- A caller who declares a server below a dialect floor, or below 2025.06 while selecting Cypher 25, fails when the renderer is constructed, before any traversal or partial output.
- No network call, driver import or server probe is introduced. The declared target stays the single source of truth.

## Alternatives considered

- Add one enum member per server release. It looks precise and becomes a product matrix that upstream does not mirror, with a prefix and capability decision for every combination.
- Ask a server for its version. It produces better answers only when a server exists, adds a driver or HTTP path to a zero-dependency library, and makes rendering depend on ambient state.
- Compare version strings or floats. String order puts `5.9` after `5.26`. Floats lose the patch component and invite rounding.
- Collapse members with equal profiles into enum aliases. It loses the identity that upstream fixtures and callers select, and it makes a later behavioural difference a breaking change.
- Treat enum membership as sufficient evidence for every construct in its family. It silently renders syntax that the declared server or the configured language cannot parse.
- Take the enum comments as the profile. At the pinned commit they disagree with the handler delegation for the default and calendar members, so the rendered behaviour and capability claims would both be wrong.

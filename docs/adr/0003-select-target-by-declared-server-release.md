# 0003: Select the target by declared server release

- Status: accepted.

## Context

- A language level is not a complete feature set. Vector `SEARCH` and full-text `SEARCH` both require
  Cypher 25 but arrived in different Neo4j releases.
- Release-named target enums combine language selection, capability claims and server releases. They
  cannot express a capability floor within one language level without adding more members.
- Prefixes are rendering facts, not proof that a server supports every construct in a language. A query
  without language-specific syntax does not need an automatic prefix.
- The runtime has no driver dependency and must not contact a server to learn its version or database
  default. The caller has to declare the release.

## Decision

- Require `server_version: str` in `Configuration`. The declared release is the single source of truth for
  capability checks, parsed into numeric `ServerVersion` components once. Reject missing, malformed or
  below-5.26 releases at construction: the 5.26 LTS is the oldest supported release, and every calendar
  release compares above it.
- Give `Language` four selections: `AUTO`, `NONE`, `CYPHER_5` and `CYPHER_25`. `AUTO` chooses the minimum
  language each query requires, and adds no prefix when no language floor applies. A pinned language always
  renders its prefix and refuses incompatible syntax.
- Let `NONE` suppress the prefix while retaining release-floor checks. The application then controls the
  database default, which can still be Cypher 5 on a release that supports Cypher 25.
- Keep one capability table with a release floor and an optional language floor per row, for example
  dynamic labels at 5.26 and vector `SEARCH` at Cypher 25 and 2026.01. The table itself is the reference,
  not this record.
- Validate prefix availability separately. `CYPHER 25` requires 2025.06 and is checked at construction and
  again in `resolve_target`. `CYPHER 5` selection arrived in 5.21, below the supported minimum, so it needs
  no enforced floor.
- Resolve one immutable target per renderer. Apply `check_requirements` to each query's analysis before
  traversal, and choose its prefix through `effective_language`. Every target uses the same immutable
  `RenderingRules` instance.
- Render the prefix outside traversal of union branches.
- Record floor sources in the [target guide](../targets.rst). The Cypher additions manual and tagged 5.21
  parser test record the `CYPHER 5` arrival date. The Select Cypher version manual establishes the
  `CYPHER 25` floor.

## Consequences

- Every caller must state a release even for a query that uses no gated syntax. In exchange, capability
  checks do not infer a release from an enum name or an absent value.
- Language selection is per query under `AUTO`. An ordinary query stays unprefixed even on a server that
  supports Cypher 25. Pinning makes that language explicit at the cost of refusing syntax outside it.
- A capability row records target policy, not a public construction API. Dynamic property writes and the
  `CALL` subquery clause currently produce requirements from the public builders.
- A new capability needs sourced language and release floors and boundary tests, not a release-specific
  rule set. Maintaining that table is a continuing cost.
- A false declared release or an uncontrolled database default can still make execution fail. Offline
  checks cannot verify either one.
- No network call, driver import or server probe is introduced. Renderers retain no per-query analysis,
  traversal or binding state.

## Alternatives considered

- Select by declared release and a separate language, as chosen. This avoids release-named enums and
  duplicate dispatch, at the cost of a required configuration value and a maintained floor table. It also
  gives up upstream target-name parity.
- Add one enum member per server release. It makes familiar names selectable, at the cost of a prefix and
  capability decision for every combination and more members as features arrive.
- Use only a language enum. It simplifies configuration, but grants later-release syntax to servers that
  cannot parse it.
- Ask a server for its version and default language. It verifies the connected server, but adds a driver or
  HTTP path to a dependency-free runtime and makes rendering depend on ambient state.
- Allow an undeclared release and assume a baseline. It shortens examples, but the inferred capability
  grant can contradict the server that will execute the query.
- Compare version strings or floats. It avoids a value type, but string order puts `5.9` after `5.26` and
  floats lose the patch component.

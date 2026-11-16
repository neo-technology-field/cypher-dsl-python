# 0007: Support upstream-maintained Python versions

- Status: accepted.

## Context

- The library should remain usable on Python versions still receiving upstream security fixes.
- Python 3.11 is the oldest release still receiving fixes, so 3.11 is the natural floor.
- Leaving the floor unstated lets a wheel claim support for an interpreter that no longer receives fixes.

## Decision

- Support stable CPython 3.11–3.15 initially. Add stable releases and retain each minor until EOL.
- Python 3.11 support lasts until October 2027. A later release can raise the floor with a release note.

## Consequences

- Keep syntax compatible with the oldest supported minor and run its unit tests in CI.
- The matrix grows when Python releases overlap. Do not multiply it by every database target.

## Alternatives considered

- A 3.12 floor shortens the matrix but excludes a supported Python release.
- A 3.10 floor supports a version already past EOL.
- Supporting 3.11 until October 2027 keeps the syntax floor low and puts one unit job per supported minor in the CI matrix for the whole period.

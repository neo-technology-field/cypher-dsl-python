# 0001: Record architecture decisions

- Status: accepted.

## Context

- The project mirrors vocabulary and rendering behaviour from a Java implementation while using a different language, API shape and test harness. A contributor needs the reasoning behind those translations, not just the resulting code.
- Some choices are expensive to reverse once published, for example the supported Python range, the dependency boundary and the build tooling.
- Decisions discussed only in chat or an issue tracker are lost when the discussion ends and cannot be found from the code they govern.

## Decision

- Keep decisions as Markdown records under `docs/adr/`, numbered in sequence with a short task-shaped title.
- Every record has the fields `Status`, `Context`, `Decision`, `Consequences` and `Alternatives considered`.
- A record is accepted, superseded or rejected by writing a new record. Fixing a typo or adding a superseding link does not need a new decision.
- Record choices that are costly to reverse or that a reasonable contributor would challenge. Do not document every class or local implementation detail.
- Index the records in the Sphinx documentation so that readers reach them from the docs tree and from links in code review.

## Consequences

- A later contributor can see why the Python surface differs from the Java one without repeating the investigation.
- Superseded records stay in place so that links keep working. The current decision is the latest accepted record for that topic.
- Each significant choice costs a short document to write and maintain. That cost is accepted for architectural decisions only.

## Alternatives considered

- Comments in the source. Close to the change, but invisible to someone choosing a design before reading code, and scattered across many files.
- A wiki or shared document store. Not versioned with the code, so it drifts and cannot be reviewed alongside the change.
- An issue tracker entry. Good for discussion, poor for a durable statement of what was decided and what it costs.

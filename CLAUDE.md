logseq-page: Project/Cypher-DSL

## Architecture decisions

Decisions are recorded as lightweight ADRs in `docs/adr/`, one decision per file, numbered
and named `NNNN-slug.md`. The project is a single distribution, so there is one directory
and no module split. `docs/adr/index.md` lists the records. They are repository
documentation and are not part of the published Sphinx site, which contains only the user
documentation.

Write one only when explicitly asked. Do not create or update ADRs on your own initiative.
If a decision looks worth recording, say so and let the user decide.

Shape: copy `docs/adr/template.md`.

- Title as a statement.
- `- Status: proposed.`, then `## Context`, `## Decision`, `## Consequences` and
  `## Alternatives considered` as bullet lists.
- Name the cost of the chosen option in `## Alternatives considered` too, so the record is
  not a sales pitch.

Keeping them:

- Put the record in `docs/adr/` and add it to the list in `docs/adr/index.md`.
- Accepted ADRs are not edited. Change a decision by adding a new ADR and setting the old
  one to `Status: superseded by NNNN`.
- Read the relevant ADRs before reversing one of them. Several record decisions that are
  easy to undo by accident, such as keeping the runtime free of driver dependencies and
  porting the upstream vocabulary rather than the Java API.

## Docstrings and comments

The bar: a reader who does not know the code understands a docstring on first read.
These rules come from repeated corrections, not taste.

- A docstring states what the thing does and the rules it holds. Nothing else.
- State behaviour, not implementation. A renderer states which dialect it emits for and
  which features it refuses, not how it walks the tree.
- Why a thing is public, and who calls it, lives with the caller. A module may name its
  purpose once at the top; members do not repeat it.
- A comment explains the code it sits on, not another module.
- Current state only. No history: no "retired", no "the old renderer".
- Literal language. No metaphors ("holds together", "bleeds into", "swallows",
  "surfaces loudly") and no stacked back-references ("the fixes its flags trigger").
- Name the type or clause instead of paraphrasing: "returns a `Rendered`", not "returns a
  result".
- Wrap prose at the configured line length (`line-length = 120`). Do not wrap at ~72.
- Multi-line docstrings: the opening `"""` and the closing `"""` each sit on their own
  line. A single-line docstring stays on one line.
- One word per concept: "clause" not "part", except the Cypher `query part`; "render" not
  "emit"; "expression" not "predicate", except the Cypher predicate that a `WHERE` takes;
  `parameter` for the occurrence and "binding" for the value attached to it.
- British English, no icons, no marketing words. See the global rules for the rest.

Read the README.md and follow the links from there.

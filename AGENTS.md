logseq-page: Project/Cypher-DSL

## Language

- British English in all written output: comments, docstrings, documentation, tests and
  user-facing strings.
- Do not change identifiers, API names or third-party terms that are fixed.
- No hype or marketing phrases in technical documents. State what happens and why it
  matters.

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

## Plans

Superpowers plans are implementation instructions for one execution, not long-living
documents.

- The plan is the spec while it runs; afterwards it is historical.
- Do not edit a plan once execution has started. Defects and ambiguities are ruled on
  during execution; the ruling governs the work but is not written back into the plan.
- Never update a plan after it has been implemented: no ticking steps, no annotations, no
  back-porting later decisions.
- Durable knowledge goes where it outlives the plan: git history, an ADR, or this file.
  Execution progress is temporary and is discarded when the last task completes. A later
  change gets a new plan, never an edit to a finished one.

## Coding style

- Google-style docstrings; the standard is in "Docstrings and comments" below.
- No icons or smileys anywhere: not in code, comments, docs, nor in output.
- Multiline strings — Cypher, prompts, messages — are triple-quoted. Never concatenate
  string literals to build one.
- Order parameters required first, optional last. A genuinely optional parameter is
  annotated `X | None = None`; never give a required parameter a `None` default.
- Do not use `*` for function parameters. Needing it signals the signature should be
  redesigned.
- A constructor accepts only what wires the object into its environment (for example a
  context or a file path). If a caller would never reasonably pass a different value, it is
  not a parameter.
- A named constant earns its place only when it is used more than once, or when the raw
  value is meaningless without a name. Single-use timeouts, batch sizes and similar values
  stay inline.

## Type seams

- Prefer a base class or a `Union` for first-party seams. Use `typing.Protocol` only to
  describe the shape of classes this project does not own, and state that reason at the
  definition.
- Never use `@runtime_checkable` `isinstance` checks against a `Protocol` for first-party
  types.

## Docstrings and comments

The bar: a reader who does not know the code understands a docstring on first read.
These rules come from repeated corrections, not taste.

- A docstring states what the thing does and the rules it holds. Nothing else.
- Substantial functions and classes carry a docstring.
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

## Documentation

- Markdown (ADRs, `docs/contributor/`): bullets, not long prose. Use sub-lists instead of
  bold text that fakes a heading.
- User documentation is the Sphinx site in `docs/*.rst`. Run `make docs` after touching a
  page or an anchor; it builds with `-W`, so a broken reference, a duplicate anchor or a
  malformed table fails.
- Keep the pages current in the same change. A new or changed function, error, option,
  rendered form or limit updates the page that documents it, and the README example stays
  what the library actually renders. A page describing behaviour the library no longer has
  is a defect, not a follow-up. `docs/llms.txt` is hand-written: update it when a page is
  added, removed or changes purpose.
- Give every concept one anchor, `.. _name:`, on the page that explains it. Explain it in
  prose before the first example on that page uses it. Later uses link to the anchor rather
  than repeat the explanation.
- Link with `` :ref:`name` `` when the target's title reads correctly in the sentence,
  `` :ref:`words <name>` `` when it does not, and `` :doc:`page` `` for a whole page. Anchor
  names are lowercase and hyphenated.
- Wrap prose at 90 columns; a URL or inline literal that cannot break may run past it.
  Keep code block lines within 80 columns.
- Cypher examples use `.. code-block:: cypher`, with Python builders in `python` blocks and
  rendered output in `text` blocks. Clause keywords start at column 0. A clause that
  depends on the line above — a `WHERE` under `MATCH` or `WITH`, a subquery body — is
  indented two spaces. Break long statements at clause boundaries, never mid-expression.
- Cypher text matches the rendered output everywhere, including prose, tests and Python
  string literals: `$name` parameters, single-quoted strings, `{key: value}` maps, no
  trailing semicolon. Keep a rendered statement on one line when it fits; break a long
  expected string in the Python source with implicit concatenation inside parentheses, not
  with newlines in the Cypher.

## Testing

- The unit suite is offline: no database, no server. Run `make test`.
- While iterating, run the targeted modules for the code you change. Run the full suite
  once before hand-over, not after every edit.

Read the README.md and follow the links from there.

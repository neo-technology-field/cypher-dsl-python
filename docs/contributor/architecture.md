# Architecture

This page describes how the package turns a finalised syntax tree into Cypher text and parameter
containers. It is for changes to the rendering internals. The public construction API and its target
options are documented separately.

## Which objects carry a statement through rendering?

The objects below take a statement from construction to text. Each is defined once here and named with the
module that owns it:

- `StatementBuilder` (`statements/builder.py`): the fluent construction stage. Every call returns a new
  immutable value, either adding a clause or updating the clause that owns the change, and `build()`
  validates the sequence and finalises it.
- `Statement` and `UnionStatement` (`statements/composition.py`): the finalised, validated clause
  sequences. These are the AST a renderer accepts.
- `Analysis` (`statements/analysis.py`): the read-only products of one analysis pass: occurrence facts,
  syntax requirements and parameter occurrences.
- `OccurrencePath` (`syntax.py`): a tuple of child indices from the root that identifies one position in
  the tree.
- `RenderingRules` (`render/rules.py`): the table that maps an AST class to its construct renderer.
- `RenderingTraversal` (`render/traversal.py`): the post-order walker that assigns occurrence paths and
  composes each node through its rule.
- `Fragment` (`render/fragments.py`): the rendered text of one child, together with the AST node that
  produced it.
- `RenderContext` (`render/context.py`): the immutable inputs one node's renderer sees: the quoting
  option and that occurrence's facts.
- `BindingCollector` (`render/bindings.py`): the per-render record of binding conflicts, bound values and
  unbound names.
- `ResolvedTarget` (`render/targets.py`): the declared release, language selection and quoting option one
  renderer uses, plus the single shared rule set.
- `Rendered` (`render/renderer.py`): one result: the complete query text, a fresh parameters dictionary
  and a fresh frozenset of unbound parameter names.

## How does a statement become `Rendered`?

`Configuration` requires a declared release in `server_version`, parses it once and validates the minimum
supported release and language availability. `Renderer.get(configuration)` resolves it through
`resolve_target`, which validates language availability again and returns an immutable `ResolvedTarget`.
The renderer retains that target and does not retain traversal or binding state.

`Renderer.render` then performs these steps:

1. It finalises the input. A `StatementBuilder` runs `build()`, which validates the clause sequence and
   returns a `Statement`. A `Statement` or `UnionStatement` is already final and passes through. This is
   what "finalised" means on this page: a validated clause sequence, not a builder still under
   construction.
2. `analyse(finalised)` returns an `Analysis` containing occurrence facts, syntax requirements and
   parameter occurrences.
3. `ResolvedTarget.check_requirements` checks the analysis requirements against the declared release and
   any pinned language. Failure stops the render before query text or result containers are returned.
4. A new `BindingCollector` records every parameter occurrence from the analysis. One bound occurrence
   resolves unbound occurrences with the same name. Two different bindings for one name raise
   `ConflictingParameterError`.
5. A new `RenderingTraversal` renders the finalised AST with the target's `RenderingRules`, the analysis
   and the `always_escape_names` option.
6. `ResolvedTarget.effective_language` selects a language for the statement and `language_prefix` turns it
   into a prefix, which the renderer prepends once, outside union branches. It returns a `Rendered`
   containing the complete text, a fresh parameters dictionary and a fresh frozenset of unbound
   parameter names.

A `Renderer` can therefore be shared. Each call owns its analysis, traversal and collector. Mutating a
result's parameters dictionary, including a list or map binding thawed into it, does not alter the AST or
a later result.

## What does each stage own?

- Analysis lives in `statements/analysis.py` and imports nothing under `render/`. It derives scope-sensitive
  facts, requirements and parameter occurrences from a finalised AST without producing Cypher text.
- `RenderingTraversal` owns post-order walking, child `Fragment` transport and occurrence path assignment.
  It owns no Cypher templates. It selects a rule only after that node's children have produced fragments.
- `RenderingRules` binds AST classes to construct renderers. Rule resolution checks the exact class and
  then the nearest registered class in its method resolution order. A missing rule raises
  `UnsupportedFeatureError`.
- Construct renderers own the text for expressions, patterns, filters, projections, UNWIND, updates and
  statements. They compose child fragments through a `RenderContext`. They own no capability checks or
  `BindingCollector`.
- Target selection owns the declared release, language selection, shared rules and name-quoting option.
  `ResolvedTarget` applies analysis requirements to that target and chooses the prefix per statement.
- `BindingCollector` owns binding conflicts, bound values and unbound names for one render. Construct
  renderers write parameter placeholders but do not collect bindings.

This separation does not make validation exhaustive. Scope and supported target rules are checked here,
while server-side semantics remain outside the library.

## How does analysis handle a syntax object used in two places?

The same node object can be declared in one `MATCH` and reused with a different role in a `CREATE`.
Object identity cannot tell those two positions apart, so analysis and traversal key their work by
`OccurrencePath` instead: a tuple of child indices counting from the root, such as `(0, 1, 2)`. Each pass
derives the same path independently from each parent's child order, and the shared AST objects are never
annotated with state from a render.

`NodePatternFacts` records the declaration role of one node pattern occurrence. `Analysis.facts_for` gives
the traversal the facts for the current path and returns `NoFacts` for an ordinary occurrence. The mapping
exposed by `Analysis` is read-only.

The cost is one more AST pass and storage for occurrence metadata. That pass and metadata replace scope
bookkeeping mixed into rendering. Rendering still walks the complete tree, so there are two AST passes
before the result is returned.

## How does structural rendering handle grouping and quoting?

Child fragments retain the AST node that produced their text. `grouped` (`render/expressions.py`) reads
`Expression.precedence` and the parent precedence to decide whether parentheses are required. It can also close an equal-precedence
child where associativity requires it. Non-expression fragments are not grouped by this rule.

Identifiers are quoted structurally from syntax values. The default adds backticks where the identifier
requires them, and `always_escape_names=True` adds them to every identifier. This is not textual search
and replacement.

`RawExpression` is different. Its text is trusted and is returned unchanged, without escaping or
validation. Raw text can bypass the structural rules and can contain syntax the library does not model.
It is not a parser or security boundary.

## How are the shared rules assembled?

`shared_bindings()` concatenates the expression, pattern, filter, projection, UNWIND, update and statement
rule bindings.
`RenderingRules.from_bindings(shared_bindings())` rejects duplicate AST classes and creates the common
immutable rule set. One `RenderingRules` instance serves every target. Construct renderers do not select
rules by release or language. `ElementId` always renders `elementId(n)`.

Target differences are requirement checks and language prefixes, not alternate rule sets. Adding a
capability floor does not add a construct renderer or a public builder.

## How do I add a construct or a capability?

To add a construct:

- Add the syntax-bearing AST class and its construction API under the owning vocabulary module.
- Add a typed construct renderer and a `RuleBinding` through `bind`.
- Register the binding in the appropriate shared binding tuple.
- Add analysis facts or a `SyntaxRequirement` when the occurrence needs scope information or has a target
  restriction.

Rule inheritance only selects the nearest registered class. A new syntax-bearing subclass still needs an
explicit rule if its rendering differs from that class. Reusing the syntax object without checking the
resulting text can silently render the wrong construct.

To add a capability, add its identity to `features.Capability`, its release and language floors to
`render.capabilities` and requirements to the analysis of the affected syntax. New target checks belong in
`render.capabilities`, with `render.targets` applying those decisions to analysis requirements. Verify the
floors against the Neo4j manual and test each boundary. The library does not discover support from a
server.

## Where does capability identity end and server/version policy begin?

`cypher_dsl.features.Capability` names syntax families independently of a release. It does not say that a
public builder exists or that a server supports the family.

`render.capabilities` owns one floor table. Each capability has a required release and an optional language
floor. Floors below the 5.26 minimum are satisfied by every supported target and record the release that
introduced the syntax family:

| Capability                | Minimum language | Minimum release |
|---------------------------|------------------|-----------------|
| `SCOPE_CLAUSES`           | none             | 5.23            |
| `DYNAMIC_PROPERTY_WRITES` | none             | 5.24            |
| `DYNAMIC_LABELS`          | none             | 5.26            |
| `VECTOR_SEARCH`           | Cypher 25        | 2026.01         |
| `FULLTEXT_SEARCH`         | Cypher 25        | 2026.09         |

`ResolvedTarget.check_requirements` refuses a capability below its release floor. A pinned language must
also meet the language floor. `effective_language` returns that pinned language, or selects the highest
required language under `Language.AUTO`. Without a language requirement, automatic selection adds no
prefix. `Language.NONE` suppresses the prefix but not release-floor checks. The application then owns the
risk that the database default cannot parse the query text.

Language availability is separate from capability floors. `CYPHER 25` requires Neo4j 2025.06 and is
checked when the configuration is built. `CYPHER 5` selection arrived in 5.21, below the 5.26 minimum, so
every supported target accepts that prefix and no floor enforces it. The target page links the manual and
tagged source evidence.

Only dynamic property writes currently produce a requirement from the supported public syntax. Other
`Capability` members describe target policy without adding construction APIs.

## Which syntax is supported?

The supported read and write subset and its restrictions are listed in the getting-started and target
pages. This architecture adds no syntax. In particular, there are no `CALL` subqueries, `SEARCH`, path
selectors or quantified path patterns. Dynamic labels and dynamic relationship types also have no public
construction API.

Releases before the 5.26 LTS are unsupported. A `Capability` member is not a promise that the library can build
the corresponding syntax. Each addition needs its AST vocabulary, validation, construct renderer and
tests, plus target rules where support differs.

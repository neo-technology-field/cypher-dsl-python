# Architecture

This page describes how the package turns a finalised statement into Cypher text and parameter
containers. The public construction API and its target options are documented separately.

A statement is a validated sequence of clauses held as syntax objects, not text. `Statement` holds one
sequence and `UnionStatement` holds branches joined by `UNION`. A `StatementBuilder` produces one and a
renderer accepts one.

## The main objects

The objects below carry a statement through the pipeline, named with the module that owns them:

- `StatementBuilder` (`statements/builder.py`): the fluent construction stage. Each call returns a new
  immutable value and `build()` validates the clause sequence into a `Statement` or `UnionStatement`
  (`statements/composition.py`), the AST a renderer accepts.
- `Analysis` (`statements/analysis.py`): one validating walk over that AST. It records the visible names
  at each point, whether each node pattern declares a name or refers to one, the syntax requirements and
  the parameter occurrences, meaning each `$name` use. It emits no Cypher text.
- `RenderingRules` (`render/rules.py`): the map from an AST class to its construct renderer.
- `RenderingTraversal` (`render/traversal.py`): the post-order walk that composes each node through its
  rule. It owns no Cypher templates.
- `Renderer` and `ResolvedTarget` (`render/renderer.py`, `render/targets.py`): the entry point, and the
  declared release, language and quoting option it renders for.
- `Rendered` (`render/renderer.py`): the result: query text, a fresh parameters dictionary and a fresh
  frozenset of unbound parameter names.

## The render pipeline

`Configuration` requires a declared release in `server_version` and validates the minimum release and
language availability once. `Renderer.get` resolves it through `resolve_target` into an immutable
`ResolvedTarget`. `Renderer.render` then performs these steps:

1. Finalise the input. A `StatementBuilder` runs `build()`. A `Statement` or `UnionStatement` is
   already final and passes through.
2. `analyse(finalised)` validates the complete tree in one walk and derives the visible names, which node
   patterns declare a name and which refer to one, the syntax requirements and the parameter occurrences.
   Analysis imports nothing under `render/` and produces no Cypher text. The same semantic rules run
   during construction.
3. `ResolvedTarget.check_requirements` checks the requirements against the declared release and any
   pinned language. Failure stops the render before query text or containers are returned.
4. A new `BindingCollector` (`render/bindings.py`) records every parameter occurrence. One bound
   occurrence resolves unbound occurrences with the same name. Two different bindings for one name
   raise `ConflictingParameterError`.
5. A new `RenderingTraversal` renders the AST with the target's rules, the analysis and the
   `always_escape_names` option. `effective_language` selects a language for the statement and
   `language_prefix` turns it into a prefix, prepended once, outside union branches.

Each call owns its analysis, traversal and collector, so a `Renderer` can be shared. Mutating a
result's parameters dictionary does not alter the AST or a later result.

Validation is not exhaustive: scope and supported target rules are checked here, server-side semantics
are not.

`shared_bindings()` concatenates the rule bindings of all construct families.
`RenderingRules.from_bindings(shared_bindings())` rejects duplicate AST classes and creates the
immutable rule set. One instance serves every target. Construct renderers do not select rules by
release or language. Target differences are requirement checks and language prefixes, not alternate
rule sets.

Rule resolution, for both rendering and semantic rules, checks the exact AST class and then the nearest
registered class in its method resolution order. A missing render rule raises
`UnsupportedFeatureError`. A new syntax-bearing subclass therefore still needs an explicit rule if its
rendering differs from that class.

## How analysis handles a syntax object used in two places

The same node object can be declared in one `MATCH` and reused with a different role in a `CREATE`.
Object identity cannot tell those two uses apart, so analysis and traversal key their work by the
occurrence instead: one appearance of a node, addressed by its `OccurrencePath` (`ast.py`), the tuple
of child indices from the root that leads to it. Each pass derives the same path independently from each
parent's child order, and the shared AST objects are never annotated with state from a render.

`NodePatternFacts` records whether one node pattern occurrence declares its name or refers to it.
`Analysis.facts_for` returns the facts for the current path, or `NoFacts` for an ordinary occurrence.
The cost is storage for occurrence metadata and two tree walks over the finalised AST: one analysis walk
and one rendering walk.

## What a scope frame carries

`ScopeFrame` (`statements/frames.py`) holds the visible names and node identities at one point in the
clause sequence. Its scope restrictions are separate facts:

- `closed`: a projection boundary, or the imports of a called body, restricts references to the frame's
  names.
- `certified`: the surrounding context is complete. The render root certifies. A called body inherits
  its enclosing certification and certifies when the call explicitly imports nothing. A `WITH`
  boundary closes the frame without certifying it.
- `reserved`: names no later clause in that frame may rebind. Imports populate it, and an inner `WITH`
  does not discard those reservations.

`SemanticRules` (`statements/rules/base.py`) selects one semantic rule per construct family through the
same method-resolution-order resolution as `RenderingRules`. Each rule validates its construct, advances
the scope frame, records the facts for the occurrence it visits and starts each nested body from the
names it imports. A called body is validated when attached to its enclosing statement and certified at
render. Every `UNION` branch starts from the same imported names.

## How grouping and quoting work

`grouped` (`render/expressions.py`) reads `Expression.precedence` and the parent precedence to decide
whether a child fragment needs parentheses. It can also close an equal-precedence child where
associativity requires it.

Identifiers are quoted structurally from syntax values: backticks where the identifier requires them,
or every identifier with `always_escape_names=True`. This is not textual search and replacement.

`RawExpression` is different. Its text is trusted and is returned unchanged, without escaping or
validation. Raw text can bypass the structural rules and can contain syntax the library does not model.
It is not a parser or security boundary.

## How to add a construct

1. Define the syntax-bearing AST class and its construction API under `clauses/` or `expressions/`.
2. Write a `SemanticRule` in the matching module under `statements/rules/` and register it in
   `shared_rules()`. Record analysis facts or a `SyntaxRequirement` there when the occurrence needs
   scope information or has a target restriction.
   - An expression that binds names for its own subtree declares them through `AstNode.local_names`.
   - A construct that rebinds names checks `reserved_name_conflict` and raises through
     `reject_reserved_redeclaration`.
   - The clause-order policy is one call to `require_appendable`, `require_read_position` or
     `require_update_position`, and one dispatch entry in `_validate_statement_clauses`.
3. Add a typed construct renderer and a `RuleBinding` through `bind` to the appropriate shared render
   bindings.
4. Put construction-decidable order and shape checks in `statements/validation.py`. Scope checks belong
   in the semantic rule.

## How to add a capability

Add its identity to `features.Capability`, its release and language floors to `render.capabilities`,
and requirements to the analysis of the affected syntax. `render.targets` applies those decisions to
analysis requirements. Verify the floors against the Neo4j manual and test each boundary. The library
does not discover support from a server.

## Where capability identity ends and release policy begins

`features.Capability` names syntax families independently of a release. It does not say that a public
builder exists or that a server supports the family. `render.capabilities` owns one floor table. Floors
below the 5.26 minimum are satisfied by every supported target and record the release that introduced
the syntax family:

| Capability                | Minimum language | Minimum release |
|---------------------------|------------------|-----------------|
| `SCOPE_CLAUSES`           | none             | 5.23            |
| `OPTIONAL_CALL`           | none             | 5.24            |
| `IN_TRANSACTIONS`         | none             | 4.4             |
| `DYNAMIC_PROPERTY_WRITES` | none             | 5.24            |
| `DYNAMIC_LABELS`          | none             | 5.26            |
| `VECTOR_SEARCH`           | Cypher 25        | 2026.01         |
| `FULLTEXT_SEARCH`         | Cypher 25        | 2026.09         |

The dynamic label floor groups node-pattern label and relationship-type syntax (5.26) with `SET` and
`REMOVE` label writes (5.24).

- `check_requirements` refuses a capability below its release floor. A pinned language must also meet
  the language floor.
- `effective_language` returns the pinned language, or selects the highest required language under
  `Language.AUTO`. Without a language requirement, automatic selection adds no prefix.
- `Language.NONE` suppresses the prefix but not release-floor checks. The application then owns the
  risk that the database default cannot parse the query text.
- Language availability is separate from the floors. `CYPHER 25` requires Neo4j 2025.06 and is checked
  when the configuration is built. `CYPHER 5` arrived in 5.21, below the 5.26 minimum, so every
  supported target accepts that prefix and no floor enforces it.

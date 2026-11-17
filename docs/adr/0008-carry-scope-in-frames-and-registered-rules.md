# 0008: Carry scope in frames and construct behaviour in registered rules

- Status: proposed.

## Context

- The CALL subquery feature added nesting to a scope model that derived scope from flat clause sequences.
  It brought a contextual mode, tracking of node identities that were not yet known, a second validation
  walk in the renderer, and `initial` and `imports` parameters threaded through the composition and
  validation modules.
- The open features nest statements inside expressions (`EXISTS`, `COUNT {}`, `COLLECT {}`), introduce
  expression-local bindings (comprehensions and list predicates), bind `YIELD` names (procedure calls) and
  change what a pattern declares (label expressions). Each would add parameters and branches in the same
  modules.
- The library is unreleased and its runtime has no dependencies, so internal types can change without a
  compatibility promise. Rendered text, parameter containers and the analysis products do not change.

## Decision

- `statements/frames.py` owns `ScopeFrame`, an immutable frame carrying six facts:
  - `names`: the visible names in binding order, or `None` when a trusted raw projection made them
    uncertifiable.
  - `closed`: a projection boundary, or the names a called body imports, restricts references to `names`.
  - `certified`: the context is complete, so import existence is checked.
  - `reserved`: what no later clause in the frame may rebind, populated by imports and surviving an inner
    `WITH`.
  - `bindings`: a name mapped to its node identity, recorded by pattern rules and read by write rules.
  - `unresolved`: names whose node identity an enclosing context may still supply.
- Rules derive the next frame from the construct in front of them, so a shared prefix can grow into several
  branches without one branch changing another.
- `statements/rules/` owns one `SemanticRule` per construct family with five hooks:
  - `bindings`: the frame transition the construct causes.
  - `validate`: the context-dependent checks against the frame in front of the construct.
  - `record`: analysis products such as capability requirements.
  - `enter_body`: the frame of a statement nested under the construct.
  - `pattern_role`: whether one node pattern occurrence declares a name or refers to one, so pattern facts
    are recorded by the rule that owns the clause.
- The registry resolves the exact class, then the method resolution order, mirroring the rendering rules. A
  completeness test discovers every concrete clause class and asserts a registered rule for it.
- Construction and render run the same rules. The builder validates each appended clause against the frame
  after its prefix, from an uncertified root frame. The analysis visitor is the single render walk. It
  validates, advances frames and records products with a certified root frame. A rule that validates the
  bodies nested under it declares `validates_body`, and the walker leaves those bodies to it rather than
  validating them again.
- `certified` is inherited and never granted by a projection. The render root certifies. A called body
  inherits its enclosing certification and certifies only when the call imports nothing explicitly. A
  `WITH` closes the frame without certifying it. Import existence is checked against closed or certified
  frames.
- `unresolved` carries the identity deferral that the contextual mode carried before. An imported name
  without a known node declaration is bound without identity, and the write rules treat it as a compatible
  endpoint until a certified frame carries the real declaration.

## Consequences

- Adding a construct is a rule class and a registration line, plus a rendering binding and, for order or
  shape rules, a construction-decidable check in `validation.py`.
- Frames are frozen values, so a branch cannot change the frame it branched from, and a frame names
  exactly what was visible at one point.
- Construct-specific scope behaviour lives in the rule modules, and frame facts are shared vocabulary.
  Label expressions or comprehensions change one rule module and the frames it reads, not the walker.
- Six frame facts have to be learned before the analysis code reads easily. The vocabulary is larger than
  the single flag it replaced.
- The identity deferral remains explicit state. It is a frame fact rather than a derivation, because the
  derivation rejected bodies that users build before attachment.
- Expression rules dispatch during the render walk only. An expression construct validates at render until
  its own task extends the construction path. The error-timing guarantee permits that, because rejection
  still precedes query text.
- A called body is validated once per render, by the outermost call's rule recursion. The walker records
  products for the body without validating it again.
- The unit suite is the oracle. Every statement that rendered before renders after, and every rejection
  keeps its site.

## Alternatives considered

- Keep the deferred machinery behind a scope-walk object. The mode flags and the second render walk remain,
  only renamed. The chosen option costs more types: six frame facts and a rule per family.
- Weaken subquery validation to the library's open-scope rule and delete the deferred machinery. It loses
  checks the documentation promises, and the maintainer asked for structure rather than fewer guarantees.
- Put scope behaviour on the syntax nodes as methods. Syntax would depend on one of its consumers,
  reversing the direction that record 0004 keeps, and every node would carry hooks most never use.
- Validate only at render and drop construction-time checks. It moves errors later than the documented
  builder behaviour allows.
- Derive the identity deferral from `names is None` instead of storing it. Measured against the previous
  behaviour, the derivation added rejections for bodies built before attachment and lost one rejection for
  a relationship name reused as an endpoint. The chosen option keeps a sixth frozen field as the price.
- Treat `closed` and `certified` as one flag. The two answer different questions, visibility and
  completeness, and every earlier attempt to combine them produced a mode flag threaded through walk
  parameters.

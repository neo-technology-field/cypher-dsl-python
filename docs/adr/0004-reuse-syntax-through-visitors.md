# 0004: Reuse syntax through visitors

- Status: accepted.

## Context

- Rendering is one consumer of the query tree. Catalogue analysis and a later OGM need to read the same
  nodes without starting a renderer.
- Placing the traversal callback under `render/` would reverse that dependency. Syntax would then depend
  on one of its consumers, and every other consumer would import the renderer to walk a tree.
- Python `==` is needed later to build Cypher predicates. It cannot also answer whether two trees are
  structurally the same. A single expression then has two meanings and a stray comparison silently changes
  the query.
- Literal inputs are ordinary Python containers. A tree that keeps a reference to a caller's list or dict
  changes after construction, which makes a repeated render produce different output.
- Bound parameter values may be driver objects. The library cannot copy them or inspect them, but it still
  has to decide whether two declarations of one name conflict.

## Decision

- Put `AstNode` and the traversal callback base in `ast.py`. `accept` calls `enter`, visits the children
  in documented syntax order, then calls `leave`. Grammar classes override `children` and do not override
  `accept`, so every consumer sees the same order.
- Keep the traversal callback private. `_Visitor` provides no-op `enter` and `leave`, and
  `_SemanticVisitor` and `RenderingTraversal` subclass it. Other tree readers recurse over `children()` and
  compare with `structurally_equal`, so the callback is not a public extension point.
- Model syntax nodes as frozen dataclasses with `eq=False` and children in tuples. Give `SymbolicName`
  normal value equality because two references to `movie` denote the same name.
- Implement `structurally_equal` as an explicit walk over node types and dataclass fields, recursing into
  tuples, lists and mappings. Value objects and frozen records compare through their own equality. The
  function never calls expression `==`.
- Snapshot sequences and string-keyed mappings into private frozen records that keep the list and map
  distinction. `thaw_value` rebuilds fresh containers on every call, and opaque objects stay by identity
  only when `allow_opaque=True`.
- Reject cyclic containers with `InvalidLiteralError` naming the container kind. Repeated non-cyclic
  subcontainers are allowed.
- Define binding equivalence with identity first and type equality second. Compare known scalars and
  containers recursively. Never compare two opaque objects through their third-party `==`.
- Make `Expression.__bool__` raise `TypeError` and leave expressions unhashable.

## Consequences

- A new consumer reads the tree without changing it and without importing the renderer. Traversal order is
  one decision in one place.
- Every literal costs one snapshot at construction. In exchange, later mutation of the caller's containers
  cannot change a rendered statement, and a literal can be rendered repeatedly with the same result.
- Opaque bindings remain caller-owned. The tree is not deeply immutable for them, and the caller must not
  change such a value during a render. That limit is documented rather than hidden by copying.
- Structural comparison has no cache, so comparing large shared trees walks them again. Catalogue
  deduplication therefore uses normalised names and typed values, not general structural hashing.
- Expressions cannot be dictionary keys or set members. Code that wants identity-keyed bookkeeping uses
  the node's `id` or an explicit normalised key.
- Adding a field to a node participates in structural comparison automatically. Tests have to state the
  difference they rely on instead of assuming that two built nodes are interchangeable.

## Alternatives considered

- Give expressions structural `__eq__` and `__hash__`. It reads well until predicate building needs `==`.
  Then either comparisons produce no Cypher or the meaning depends on context, and hashing invites dict
  lookups with ambiguous truth values.
- Keep the callback base in `render/`. It avoids one module, at the cost of syntax depending on rendering
  and every other consumer importing the renderer.
- Export the traversal callback as a public extension point. It makes every grammar change a compatibility
  promise to callers who do not need one. Analysis and rendering can share the private callback without
  that promise.
- Retain references to the input containers instead of copying. It avoids the snapshot cost and lets
  caller mutation change an already built statement, which defeats deterministic rendering and shared
  subtrees.
- Deep-copy every bound object. It invokes third-party state the library does not own, can fail for driver
  handle types and breaks the rule that drivers stay outside the runtime.

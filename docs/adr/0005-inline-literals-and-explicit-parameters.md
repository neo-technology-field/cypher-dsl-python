# 0005: Inline literals and explicit parameters

- Status: accepted.

## Context

- Cypher distinguishes a name position from a value position. In `RETURN m`, `m` is a variable. In `RETURN 'm'`, `m` is data. A Python string cannot mean both at the same call site without a rule.
- Query text is built by concatenation of fragments. Any value copied into that text can end a literal or a clause if it is not escaped, so string interpolation of user data is not acceptable.
- A parameter is a placeholder plus a binding. The same name can occur several times, may be bound in one place and unbound in another, and must not turn `True` into `1` or a list into a tuple.
- Bindings are request data. They change between executions of the same query, and a shared syntax tree must not absorb them. Two threads rendering the same tree through one renderer must not see each other's values.
- Bound values can be driver-owned objects. The library can neither copy nor inspect them, and must not let a third-party equality method decide whether two declarations conflict.
- Inline bytes have no byte-literal syntax this library claims. Temporal values need the constructor that matches their awareness, not a generic string.
- Cypher decodes `\uxxxx` inside a backticked name as a UTF-16 code point. A name that carries that text is not inert data: `\u0060` becomes a backtick when Cypher reads it. The same applies to a temporal zone key, which is appended inside a quoted constructor argument.
- Cypher treats a keyword in an expression position as syntax. A variable named `true` must be quoted or it becomes the Boolean literal.

## Decision

- Coerce projection input by kind. A bare `str` becomes a `Variable`. An `Expression` passes through. A `NamedExpression` contributes its variable through `as_expression()`. Anything else goes through `lit()`. String values in projections require `lit()`.
- Snapshot every literal at construction. Freeze sequences and string-keyed mappings into private records, reject unsupported types, cyclic containers, non-string map keys and non-finite floats.
- Reject an alias applied to an already aliased expression. The `AliasedExpression` constructor enforces it, so the fluent method and direct construction both fail instead of rendering two `AS` words for one item.
- Provide explicit parameters only. `param(name)` is unbound. `param(name, None)` is bound to null. A private sentinel keeps those apart. No automatic parameterisation is performed in this release.
- Collect bindings per render in `BindingCollector`. An unbound occurrence is recorded unless the name already has a bound value. A bound occurrence records the value and removes the name from the unbound set, so a later bound occurrence resolves an earlier unbound one. A different binding for the same name raises `ConflictingParameterError`.
- Compare bindings with `same_binding`. Types must match, so `True` and `1`, and `1` and `1.0`, are different bindings. Opaque values compare by identity only. An unbound occurrence is not a binding at all, so it does not compete with a null binding.
- Keep no binding storage on `StatementBuilder`, `Statement` or `UnionStatement`. Each `Rendered` result owns a fresh mutable dictionary and a fresh frozenset. Thawed containers are rebuilt per result.
- Reject inline bytes from `lit()` rendering with `InvalidLiteralError` that names `param()` as the supported route. Bound bytes pass through unchanged.
- Render null, booleans, integers and finite floats in that order. Quote strings while escaping backslash, both quote characters and the named control escapes.
- Render standard-library `date`, `datetime`, `time` and `timedelta` through `date()`, `localdatetime()` or `datetime()`, `localtime()` or `time()`, and `duration()`. Pass the complete constructor argument through the string-escaping primitive. A negative duration carries one leading sign over absolute components. A zone key is validated as an IANA-style name before it is appended, so an arbitrary `ZoneInfo` key cannot become constructor syntax.
- Quote identifiers structurally: bare when the plain form is legal, backticked otherwise, embedded backticks doubled, empty names and control characters rejected. Reject any `\uxxxx` or `\Uxxxxxxxx` escape sequence in an identifier rather than decoding it, and reject one that decodes to a control character. Identifiers are literal names, so a caller who wants the backtick passes the character.
- Quote a name that case-insensitively matches a Cypher keyword. Parameter names are the one exception, because the leading `$` already introduces a name token. A variable, alias or map key named `true`, `null` or `match` is therefore quoted under the default settings.
- Document parameters as the route for request data. Correct escaping does not make inline request data desirable in logs or for query-cache reuse.

## Consequences

- A caller who wants a variable name writes a string, and a caller who wants a string value writes `lit()`. The distinction stays visible at the call site.
- Bindings cannot leak between renders or threads, at the cost of collecting them again on every render.
- An unbound occurrence that is later bound to null renders one null binding. This differs from Java, which treats no value versus null as a conflict. Here an unbound occurrence makes no value claim, so a bound null settles it. A caller who needs a value at execution time must not also bind null.
- Conflict detection happens during rendering. The renderer raises before returning a result, so a caller never receives the first half of a conflicting query.
- Opaque bindings remain caller-owned. The caller must not mutate them during a render, and the library cannot promise deep immutability for them.
- Inline data always costs a full query string. A caller who wants plan reuse and stable query text has to use parameters.
- A `ZoneInfo` input depends on the process having zone data, as any Python date-time formatting does. A key that is not IANA-shaped is refused rather than sent to the server.
- Keyword quoting changes some rendered text, for example `` RETURN `true` `` instead of `RETURN true`. The second form is a literal, not the variable the caller asked for.
- An identifier containing an escape-looking sequence is refused even if the caller meant the visible characters. Cypher would decode it, so accepting it would change the name.

## Alternatives considered

- Interpolate values with `str()` or an f-string. It is shorter to write and makes value text indistinguishable from query syntax, which is the defect this design exists to prevent.
- Decode `\uxxxx` in identifiers and then double the resulting backtick. It keeps the query safe, at the cost of silently changing the name the caller supplied. Rejecting is explicit and keeps the name literal.
- Leave keyword quoting to `always_escape_names`. It makes correctness depend on a non-default option, and the default output would still turn a variable into a literal.
- Quote parameter names by the same keyword rule. The dollar sign already separates the name from expression syntax, and quoting `$data` differs from upstream for no safety gain.
- Treat every bare string in a projection as a literal. Then `returning("m")` cannot mean the obvious variable, and every name reference needs an extra wrapper.
- Parameterise everything automatically. It changes rendered output and parameter names without the caller asking, and makes a write query's text depend on a policy the caller cannot see.
- Store bindings on the statement. It avoids a collector object and makes the same tree unusable for a second set of values.
- Compare bindings with Python `==`. It merges `True` and `1`, can raise on arrays, and invokes third-party equality on driver objects.
- Let an unbound occurrence conflict with a null binding, matching Java's catalog behaviour. It reports a conflict for a tree that has one unambiguous binding, and forces callers to choose between binding now and binding later.

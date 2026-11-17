# 0002: Port vocabulary and rendering behaviour, not the Java API

- Status: accepted.

## Context

- The Java Cypher-DSL is the reference implementation for this project. It has years of tested rendering
  behaviour, a dialect enum and a catalogue model that a Python project cannot reproduce from the Cypher
  grammar alone.
- Its public API is shaped by Java: interfaces, builders with bean-style setters, JUnit and AssertJ in
  tests, annotation processing and Spring or QueryDSL adapters around the core.
- A Python consumer expects functions such as `match` and `returning`, keyword arguments and an immutable
  fluent chain. Copying Java type names and call shapes would produce code that is foreign in both
  languages.
- Rendering output and parameter naming are observable and can be compared across languages. Class layout
  and test framework cannot.

## Decision

- Mirror upstream vocabulary where it is part of the rendered result or the declared configuration:
  clause order, default escaping and pretty-print settings, parameter naming rules and function names.
- Design the Python surface independently: factory functions in snake_case, expression objects with
  Python operators, immutable composition and keyword arguments for configuration. Do not expose Java
  interfaces, abstract base classes, visitor names or bean-style getters.
- Port scenarios and expected output, not test classes, JUnit annotations or AssertJ call shapes. Keep
  the upstream class, nested context and method in a comment beside the port so that it stays traceable.
- Preserve a Java distinction only when it changes rendered Cypher or declared target behaviour. A
  distinction that exists only for Java typing or adapters stays out.
- Exclude Java-only infrastructure: annotation processing, generated model classes, Spring and QueryDSL
  adapters, native-image configuration and JUnit extensions.
- State intentional output differences in the ported test rather than silently changing an expected
  string.

## Consequences

- Parity is measured on rendered Cypher text and parameter bindings. That is the part both implementations
  can prove without sharing a runtime.
- Upstream's target enum names encode releases and cannot express capability floors inside one language
  level. Python selects a declared server release and a language instead of mirroring those names.
- Documentation has to explain the translation from a Java example to its Python equivalent. Pointing at
  the Java class is not enough.
- A later upstream change is not absorbed by merging. It is adopted deliberately, with its expected output
  rechecked.
- Python-only affordances, such as overloaded operators, cannot be compared with a Java method call. They
  need their own tests and cannot count as upstream parity on their own.
- Some helper and adapter tests are not ported. Nothing counts them, so the gap is a known hole rather
  than a hidden omission.

## Alternatives considered

- Transliterate the Java API into Python. It keeps names familiar to Java users, at the cost of unidiomatic
  Python, Java-only types in the public surface and a permanent translation layer for adapters this
  project does not support.
- Run the Java implementation through a bridge and wrap it. It would reuse the renderer directly, but adds
  a JVM to every install and defeats the point of a dependency-free Python library.
- Implement only from the Cypher grammar and specification. It avoids inheriting Java API choices, but
  throws away tested edge cases and leaves no provenance for expected output.

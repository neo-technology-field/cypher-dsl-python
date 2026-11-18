Supported Cypher
================

This page maps the library's surface to the groups and terms of the Cypher 25
`cheat sheet <https://neo4j.com/docs/cypher-manual/25/cheat-sheet/>`_. Everything listed
under a supported heading can be built and rendered; constraints that apply are stated
where the feature appears. The two lists at the end carry what this release does not
cover, split into what is not yet implemented and what is not planned.

Release floors are a separate matter: a supported feature can still require a newer
declared release. :doc:`targets` explains how the declaration selects syntax.

Read
----

``MATCH``
~~~~~~~~~

``node()`` builds a node pattern with one or more labels, an optional variable and an
optional property map. A label is required.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node

    movie = node("Movie", name="m")
    statement = match(movie).returning(movie["title"])
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (m:Movie) RETURN m.title

Relationship patterns take one type or a :ref:`type expression <label-expression>` and a
direction. A chain extends from its current endpoint, so a multi-relationship path stays
one pattern.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node

    person = node("Person", name="p")
    acted = person.relationship_to(node("Movie"), "ACTED_IN")
    statement = match(acted).returning(person["display_name"])
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)-[:ACTED_IN]->(:Movie) RETURN p.display_name

``OPTIONAL MATCH``
~~~~~~~~~~~~~~~~~~

A later clause can optionally match from a variable an earlier clause bound.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node

    person = node("Person", name="p")
    directed = person.relationship_to(node("Movie"), "DIRECTED")
    statement = (
        match(person)
        .optional_match(directed)
        .returning(person["display_name"])
    )
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)
    OPTIONAL MATCH (p:Person)-[:DIRECTED]->(:Movie)
    RETURN p.display_name

``WHERE``
~~~~~~~~~

Conditions build from comparison operators, ``&`` (AND), ``|`` (OR) and ``~`` (NOT), and
from ``in_``, ``starts_with``, ``ends_with`` and ``contains``. Python cannot overload
``and``, ``or`` and ``not``, so the symbol forms are the operators; a condition read from
a parameter needs ``condition()``.

.. code-block:: python

    from cypher_dsl import (
        Configuration,
        Renderer,
        match,
        node,
        param,
        starts_with,
    )

    person = node("Person", name="p")
    statement = (
        match(person)
        .where(
            (person["age"] < param("max_age"))
            & starts_with(person["uid"], "A")
        )
        .returning(person["uid"])
    )
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) WHERE p.age < $max_age AND p.uid STARTS WITH 'A'
    RETURN p.uid

``has_label`` tests a node's labels or a relationship's type against a
:ref:`label expression <label-expression>`. The colon form works on every supported
release:

.. code-block:: python

    from cypher_dsl import (
        Configuration,
        Renderer,
        has_label,
        label,
        match,
        node,
    )

    person = node("Person", name="p")
    report = node("Person", name="c").relationship_to(person, name="r")
    statement = (
        match(report)
        .where(has_label(person, label("Manager") | label("Director")))
        .returning(
            person["uid"], has_label(report, "WORKS_FOR").alias("reports")
        )
    )
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (c:Person)-[r]->(p:Person) WHERE p:Manager|Director
    RETURN p.uid, r:WORKS_FOR AS reports

``is_labeled`` and ``is_not_labeled`` render the ``IS [NOT] LABELED`` form, which
Neo4j 2026.04 introduced for Cypher 25. Under ``Language.AUTO`` the statement then
selects the ``CYPHER 25`` prefix:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, is_not_labeled, match, node

    person = node("Person", name="p")
    statement = (
        match(person)
        .where(is_not_labeled(person, "CEO"))
        .returning(person["uid"])
    )
    renderer = Renderer.get(Configuration(server_version="2026.10"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    CYPHER 25 MATCH (p:Person) WHERE p IS NOT LABELED CEO RETURN p.uid

Path pattern expressions
~~~~~~~~~~~~~~~~~~~~~~~~

``path_pattern`` turns a relationship chain into a boolean: it is true when the chain
matches at least once. It is a predicate, so ``&``, ``|`` and ``~`` combine it with
other conditions. Every named node and relationship in the chain must reference a name
an earlier clause binds; the expression declares none of its own:

.. code-block:: python

    from cypher_dsl import (
        Configuration,
        Renderer,
        lit,
        match,
        node,
        path_pattern,
    )

    person = node("Person", name="p")
    works_for = person.relationship_to(
        node("Person", properties={"uid": lit("p1")}), "WORKS_FOR"
    )
    statement = (
        match(person)
        .where(path_pattern(works_for))
        .returning(person["uid"])
    )
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: text

    MATCH (p:Person) WHERE (p:Person)-[:WORKS_FOR]->(:Person {uid: 'p1'})
    RETURN p.uid

A projection item is not a boolean position: project ``~path_pattern(...)`` instead. A
pattern that binds its own names or needs clauses of its own needs the ``exists``
subquery form. The scope rules are documented with the read clauses: see
:ref:`path pattern expressions <path-pattern-expression>`.

``RETURN``
~~~~~~~~~~

Projections take expressions, aliases, ``DISTINCT``, ``ORDER BY``, ``SKIP`` and
``LIMIT``.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node

    movie = node("Movie", name="m")
    statement = (
        match(movie)
        .returning(movie["title"])
        .distinct()
        .order_by(movie["title"])
        .skip(10)
        .limit(5)
    )
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (m:Movie)
    RETURN DISTINCT m.title ORDER BY m.title SKIP 10 LIMIT 5

``WITH``
~~~~~~~~

``WITH`` ends one query part and starts the next. Only the names it projects are
available afterwards; a structured projection item needs an alias.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, desc, match, node

    person = node("Person", name="p")
    statement = (
        match(person)
          .with_(person)
          .order_by(desc(person["rating"]))
          .limit(1)
          .returning(person["display_name"])
    )
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)
    WITH p ORDER BY p.rating DESC LIMIT 1
    RETURN p.display_name

Write
-----

``CREATE``
~~~~~~~~~~

``CREATE`` writes node patterns and relationship patterns. A write relationship needs one
plain type and a direction. The property map is explicit entries, a map expression, a map
literal or a whole-map parameter; a whole-map variable needs ``SET`` instead.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, create, node, param

    statement = create(
                  node("Person", name="p", properties={"email": param("email")})
                  )
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    CREATE (p:Person {email: $email})

``MERGE``
~~~~~~~~~

``MERGE`` takes one identity pattern with explicit properties and at most one ``ON
CREATE`` and one ``ON MATCH`` action.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, assign, merge, node, param

    person = node("Person", name="p", properties={"email": param("email")})
    statement = (
        merge(person).on_match(assign(person["seen_at"], param("now")))
    )
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MERGE (p:Person {email: $email})
        ON MATCH SET p.seen_at = $now

``SET``
~~~~~~~

``assign`` replaces a value, ``update_properties`` patches a map, and ``set_labels`` adds
labels.

.. code-block:: python

    from cypher_dsl import (
        Configuration,
        Renderer,
        assign,
        match,
        node,
        set_labels,
    )

    person = node("Person", name="p")
    statement = (
        match(person)
        .set_(assign(person["age"], 36), set_labels(person, "Employee"))
        .returning(person["display_name"])
    )
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) SET p.age = 36, p:Employee RETURN p.display_name

``REMOVE``
~~~~~~~~~~

``REMOVE`` takes property references and label updates.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, set_labels

    person = node("Person", name="p")
    statement = (
        match(person)
        .remove(person["age"], set_labels(person, "Employee"))
        .returning(person["display_name"])
    )
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) REMOVE p.age, p:Employee RETURN p.display_name

``DELETE``
~~~~~~~~~~

``delete`` removes named elements; ``detach_delete`` also removes their relationships.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node

    person = node("Person", name="p")
    statement = match(person).detach_delete(person)
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) DETACH DELETE p

Patterns
--------

Node patterns
~~~~~~~~~~~~~

``node()`` takes one primary label or a label expression, an optional variable and an
optional property map. ``with_labels`` extends a pattern with plain labels.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node

    person = node("Person", name="p")
    statement = (
        match(person.with_labels("Employee"))
        .returning(person["display_name"])
    )
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person:Employee) RETURN p.display_name

Label expressions
~~~~~~~~~~~~~~~~~

:func:`~cypher_dsl.label` terms combine with ``&`` (both), ``|`` (either) and ``~`` (not,
rendered as ``!``), plus ``ANY_LABEL`` for the ``%`` wildcard. The same grammar serves
node labels and relationship types.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, label, match, node

    pattern = node(label("Movie") | label("Person"), name="n")
    statement = match(pattern).returning(pattern["title"])
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (n:Movie|Person) RETURN n.title

A label expression states what to match, so ``CREATE`` and ``MERGE`` reject it and take
plain labels instead.

Relationship patterns
~~~~~~~~~~~~~~~~~~~~~

A relationship takes one type or a union of types. Adjacent relationships in a chain meet
at the same node pattern object, so a chain cannot describe two different nodes under one
name.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, label, match, node

    credits = node("Person", name="p").relationship_to(
        node("Movie"), label("ACTED_IN") | label("DIRECTED"), name="r"
    )
    statement = match(credits).returning(credits["character"])
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)-[r:ACTED_IN|DIRECTED]->(:Movie) RETURN r.character

Composed queries
----------------

``UNION``
~~~~~~~~~

``union`` combines whole statements; ``all=True`` renders ``UNION ALL``. Known projection
names must line up by position.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, union

    person = node("Person", name="n")
    movie = node("Movie", name="n")
    statement = union(
        match(person).returning(person),
        match(movie).returning(movie),
    )
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (n:Person) RETURN n UNION MATCH (n:Movie) RETURN n

Subqueries and procedures
-------------------------

``CALL``
~~~~~~~~

A ``CALL`` subquery is a finalised statement run once per outer row. The variable scope
clause always renders, and ``imports`` or ``import_all`` pass outer names in.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, name, node

    person = node("Person", name="p")
    movie = node("Movie", name="m")
    acted = person.relationship_to(movie, "ACTED_IN")
    body = match(acted).returning(
        movie["title"].alias("title")
    ).build()
    statement = match(person).call(
        body, imports=("p",)
    ).returning(name("title"))
    renderer = Renderer.get(
        Configuration(server_version="5.26", pretty_print=True)
    )
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)
    CALL (p) {
      MATCH (p:Person)-[:ACTED_IN]->(m:Movie) RETURN m.title AS title
    }
    RETURN title

``OPTIONAL CALL`` renders the optional form of the same call.

``CALL ... IN TRANSACTIONS``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``in_transactions`` runs the body in inner transactions. Pass ``True`` for the bare
modifier, or a positive row count for ``OF ... ROWS``.

.. code-block:: python

    from cypher_dsl import (
        Configuration,
        Renderer,
        create,
        fn,
        name,
        node,
        unwind,
    )

    body = create(node("Clone", properties={"uid": name("item")})).build()
    statement = (
        unwind(fn("range", 1, 100_000), name("item"))
        .call(body, imports=("item",), in_transactions=5_000)
        .returning(name("item"))
    )
    renderer = Renderer.get(
        Configuration(server_version="5.26", pretty_print=True)
    )
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    UNWIND range(1, 100000) AS item
    CALL (item) {
      CREATE (:Clone {uid: item})
    } IN TRANSACTIONS OF 5000 ROWS
    RETURN item

Procedures
~~~~~~~~~~

``call_procedure`` names the procedure in one dot-qualified string; ``yielding`` keeps
the named output columns.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, call_procedure, name, param

    statement = (
        call_procedure("dbms.checkConfigValue", param("setting"), "true")
        .yielding("valid")
        .returning(name("valid"))
    )
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    CALL dbms.checkConfigValue($setting, 'true') YIELD valid RETURN valid

``EXISTS``
~~~~~~~~~~

``exists`` builds an existential subquery expression. It is a predicate, so it filters in
``WHERE``, projects in ``RETURN`` and combines with ``&``, ``|`` and ``~``. The body is a
read subquery that sees the enclosing scope without a scope clause.

.. code-block:: python

    from cypher_dsl import (
        Configuration,
        Renderer,
        exists,
        match,
        node,
        param,
    )

    person = node("Person", name="p")
    dog = node("Dog", name="d")
    walked = match(person.relationship_to(dog, "HAS_DOG")).where(
        dog["name"] == param("dog_name")
    )
    statement = match(person).where(exists(walked)).returning(person["name"])
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: text

    MATCH (p:Person)
    WHERE EXISTS {
            MATCH (p:Person)-[:HAS_DOG]->(d:Dog) WHERE d.`name` = $dog_name
    }
    RETURN p.`name`

The scope rules, the pattern-element form and the limits are on :doc:`subqueries`.

Expressions
-----------

Comparisons, boolean operators, arithmetic, ``IN``, string predicates, literals,
parameters, lists, maps and subscripts are accepted wherever the grammar takes a value.
A property read can use a computed key for a dynamic property name:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param

    person = node("Person", name="p")
    statement = match(person).where(person[param("prop")] > 40).returning(
        person["display_name"]
    )
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) WHERE p[$prop] > 40 RETURN p.display_name

A boolean read from a parameter needs ``condition()``. A bare ``and``, ``or`` or ``not``
cannot be overloaded, so conditions combine with ``&``, ``|`` and ``~``.

Functions
---------

Any function is callable through ``fn()``. ``count``, ``element_id`` and ``asterisk``
cover ``count(...)``, ``elementId(...)`` and the ``*`` projection:

.. code-block:: python

    from cypher_dsl import (
        Configuration,
        Renderer,
        count,
        element_id,
        match,
        node,
    )

    person = node("Person", name="p")
    statement = match(person).returning(
        count(person).alias("people"), element_id(person).alias("identifier")
    )
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) RETURN count(p) AS people, elementId(p) AS identifier

Targets
-------

The rendered text depends on the declared release and language. :doc:`targets` explains
the floors, the ``CYPHER 5`` and ``CYPHER 25`` prefixes, and identifier escaping. A
supported feature that needs a newer release is rejected at render time when the
declaration is too old.

.. _support-not-yet:

Not yet
-------

- ``COUNT { ... }`` and ``COLLECT { ... }`` — subquery expressions.
- ``SEARCH n IN (VECTOR INDEX idx FOR $v) SCORE AS s``, and the ``FULLTEXT`` variation —
  vector and full-text search.
- ``CASE WHEN ... THEN ... ELSE ... END`` — a conditional expression.
- ``p.email =~ '...'`` — a regular expression match.
- ``a || b`` — string concatenation.
- ``XOR`` — exclusive disjunction between conditions.
- ``[x IN coll WHERE p | e]`` and ``reduce()`` — list comprehension and fold.
- ``all(x IN coll WHERE p)``, ``any``, ``none``, ``single`` — quantified list
  predicates.
- ``p{.uid, .name}`` — map projection.
- ``val IS [NOT] :: INTEGER`` — a type predicate.
- ``FOREACH (x IN list | SET ...)`` — an updating loop.
- ``FILTER``, ``LET`` — clauses that filter or bind without a ``WHERE`` or ``WITH``.
- ``GROUP BY`` — explicit grouping keys.
- ``FOR x IN [1, 2, 3]`` — a clause that expands a list into rows.
- ``NEXT`` and standalone ``WHEN ... THEN ... ELSE ...`` — sequential and conditional
  queries.
- ``$()``, ``$any()``, ``$all()`` and ``SET n:$(expr)`` — dynamic labels and types.
- ``-[:R]->{1,5}`` — quantified relationships; ``((a)-[:R]->(b)){1,5}`` — quantified
  path patterns.
- ``MATCH p = (...)``, ``shortestPath()``, ``allShortestPaths()``, ``SHORTEST k``, path
  selectors and path modes — path variables and path finding.
- ``OFFSET`` — the ``SKIP`` synonym.
- ``FINISH`` — ending a query without a result.
- ``USING INDEX``, ``INDEX SEEK``, ``SCAN``, ``JOIN`` — planner hints.
- ``UNION DISTINCT`` and brace-grouped unions. ``UNION`` and ``UNION ALL`` are supported.
- ``IN 4 CONCURRENT TRANSACTIONS OF 100 ROWS`` — concurrent inner transactions. Plain
  ``IN TRANSACTIONS`` and ``OF ... ROWS`` are supported.
- ``INSERT`` — the synonym of ``CREATE`` that requires ``&`` between labels.

.. _support-not-planned:

Not planned
-----------

- ``MATCH (n)`` — an unlabelled node pattern. Every node pattern states what it
  matches, and that is deliberate: the builders never produce a label-free match.
- ``LOAD CSV`` — it's a PoC tool at best. Good for demos. Has no place in a DSL.
  builder.
- ``EXPLAIN`` and ``PROFILE`` — developer tooling.
- ``-[:R*1..3]->`` — the legacy variable-length syntax, superseded by quantified path
  patterns.
- ``CREATE INDEX``, ``CREATE CONSTRAINT`` and graph types — schema management, not query
  construction.
- ``SHOW INDEXES`` and the other ``SHOW`` commands — administrative and introspection
  commands; procedure calls cover the introspection the builders support.
- ``USE database`` — the executing session selects the database. ``USE`` serves shells
  and the Browser, and a builder cannot validate a graph it never connects to.

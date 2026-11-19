Getting started
===============

The library builds syntax objects. Rendering turns them into Cypher text and a separate
parameter dictionary. Nothing here talks to a server, so the examples run in a unit test
without a database.

Install
-------

The distribution name is ``cypher-dsl`` and the import name is ``cypher_dsl``. Install it from PyPI:

.. code-block:: shell

    pip install cypher-dsl

In a uv project, use ``uv add cypher-dsl``. The package has no runtime dependencies and ships ``py.typed``.

Build and render a statement
----------------------------

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param

    movie = node("Movie", name="m")
    statement = (
        match(movie)
        .where(movie["released"] < param("year", 2000))
        .returning(movie["title"])
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    first = renderer.render(statement)
    second = renderer.render(statement)

    print(first.cypher)
    print(first.parameters)
    print(first.parameters is second.parameters)

.. code-block:: text

    MATCH (m:Movie) WHERE m.released < $year RETURN m.title
    {'year': 2000}
    False

.. _statement:
.. _clause:

The value you build is a statement: a sequence of clauses, here ``MATCH``, ``WHERE`` and
``RETURN``. A clause is one Cypher keyword together with its content.

Rendering does not change the statement, and every render returns its own parameter
dictionary: changing one result's dictionary leaves the statement and other results alone.

To reuse one query with different request values, build its parameter with no value:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param

    movie = node("Movie", name="m")
    statement = (
        match(movie)
        .where(movie["released"] < param("year"))
        .returning(movie["title"])
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    rendered = renderer.render(statement)

    print(rendered.cypher)
    print(rendered.parameters)
    print(sorted(rendered.unbound_parameters))

.. code-block:: text

    MATCH (m:Movie) WHERE m.released < $year RETURN m.title
    {}
    ['year']

``param("year")`` is an unbound parameter: the render reports it in
``unbound_parameters``, and the code that runs the query supplies the value. The text is
identical for every request, so it can be cached and logged. With the Neo4j driver, the
call is ``session.run(rendered.cypher, {"year": 1999})``. See :doc:`running` for the
handoff and :doc:`parameters` for the binding rules.

Read related nodes
------------------

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, desc, match, node, param

    person = node("Person", name="p")
    movie = node("Movie", name="m")
    acted_in = person.relationship_to(movie, "ACTED_IN", name="r")

    statement = (
        match(acted_in)
        .where(movie["released"] > param("since", 2000))
        .returning(person["display_name"].alias("actor"), movie["title"])
        .order_by(desc(movie["released"]))
        .limit(10)
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)-[r:ACTED_IN]->(m:Movie)
      WHERE m.released > $since
    RETURN p.display_name AS actor, m.title
      ORDER BY m.released DESC LIMIT 10

``relationship_from`` and ``relationship_with`` build incoming and undirected patterns.
``with_labels`` adds labels to an existing pattern instead of creating a second one.

.. _query-part:

Filter before narrowing the next query part
-------------------------------------------

An ordinary ``WITH`` ends one query part and starts the next, and owns its ``WHERE``.
That filter can use both incoming variables and
projected aliases, even when the incoming variable is not passed to the next clause:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, name, node, param

    person = node("Person", name="p")
    statement = (
        match(person)
        .with_(person["uid"].alias("uid"))
        .where(person["rating"] > param("min_rating"))
        .returning(name("uid"))
    )
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) WITH p.uid AS uid WHERE p.rating > $min_rating RETURN uid

Only ``uid`` is available after this ``WITH``. A later ``returning(person)`` is rejected.
With ``DISTINCT`` or an aggregate such as ``count``, the owning filter is restricted to
projected names as well. A filter cannot restore a name discarded by an earlier ``WITH``.
The library checks which names each clause may use. What a server checks, such as missing
labels or property types, is not covered.

Write and update data
---------------------

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, assign, merge, node, param

    person = node("Person", name="p", properties={"email": param("email")})
    upsert = (
        merge(person)
        .on_create(assign(person["created_at"], param("now")))
        .on_match(assign(person["seen_at"], param("now")))
        .returning(person)
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(upsert).cypher)

.. code-block:: cypher

    MERGE (p:Person {email: $email})
      ON CREATE SET p.created_at = $now
      ON MATCH SET p.seen_at = $now
    RETURN p

Updating an existing node uses ``set_`` and an attached ``WHERE``:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, assign, match, node, param

    person = node("Person", name="p")
    statement = (
        match(person)
        .where(person["email"] == param("email"))
        .set_(assign(person["rating"], param("rating")))
        .returning(person["display_name"])
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)
      WHERE p.email = $email
    SET p.rating = $rating
    RETURN p.display_name

A bulk write takes the rows as a bound parameter and binds a :ref:`variable <variable>`
named ``row`` for the
clause body:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, name, node, param, unwind

    row = name("row")
    properties = {"email": row["email"], "display_name": row["display_name"]}
    statement = (
        unwind(param("rows"), row)
        .create(node("Person", properties=properties))
        .returning(row["email"])
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    UNWIND $rows AS `row`
    CREATE (:Person {email: `row`.email, display_name: `row`.display_name})
    RETURN `row`.email

``DELETE`` and ``DETACH DELETE`` are available through ``delete`` and ``detach_delete``.
Deleting a node with relationships requires the detached form.

An already-bound node can be reused as a compatible relationship endpoint in ``CREATE``
or ``MERGE``. A standalone write node declares a new variable, so ``match(person).merge(person)``
is rejected. A conflicting label or property declaration on a bound endpoint is rejected
rather than silently discarded. Every written relationship needs one type. Only ``CREATE``
also requires a direction.

Combine conditions with the DSL operators
-----------------------------------------

Python cannot overload ``and``, ``or`` or ``not``, so a condition tree uses ``&``, ``|``,
``^`` and ``~``. Keep each comparison in its own parentheses, because Python binds ``&``
tighter than ``>``:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param

    person = node("Person", name="p")
    statement = (
        match(person)
        .where(
            (person["rating"] > param("min_rating", 4.0))
            & (person["email"] == param("email", "ada@example.com"))
        )
        .returning(person["display_name"])
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)
      WHERE p.rating > $min_rating AND p.email = $email
    RETURN p.display_name

The renderer adds parentheses where Cypher precedence requires them, so the text follows
the Cypher precedence rules rather than the layout of the Python source.

Comparing an expression with ``None`` builds ``IS NULL``:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param

    person = node("Person", name="p")
    statement = (
        match(person)
        .where(
            (person["nickname"] == None)
            & (person["rating"] > param("min_rating", 4.0))
        )
        .returning(person["display_name"])
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)
      WHERE p.nickname IS NULL AND p.rating > $min_rating
    RETURN p.display_name

.. _raw-expression:

Escape to raw expression text
-----------------------------

``raw(text)`` emits trusted expression text unchanged. It covers expression syntax with no
builder in this release, and expression text that arrives already written. A regex match
has ``matches``; here the whole predicate is the text:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, condition, match, node, raw

    person = node("Person", name="p")
    statement = (
        match(person)
        .where(condition(raw("p.email =~ '(?i)ada.*'")))
        .returning(person)
    )
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) WHERE p.email =~ '(?i)ada.*' RETURN p

Nothing escapes or validates that text, and a server may still reject it. Supply only
expression text that you have checked yourself. It is an expression, so it cannot express a
whole clause. A raw expression used where a predicate belongs goes through ``condition()``.
To call a function by name, use ``fn``, described under :ref:`functions`.

What is not available
---------------------

- No OGM, driver connection, transaction or schema installation. Those belong to the
  caller's application or test harness.
- No ``SEARCH``, path selectors, quantified path patterns or catalogue analysis in
  this release.
- No Cypher parser. The input is Python construction, not query text.
- No automatic parameterization. A caller decides what becomes a parameter.
- No inline bytes literal. Bind ``bytes`` with ``param()`` and pass it to the driver.
- No complete semantic validator. Clause order, known references and bindings are checked.
  Missing labels, property types and server-side semantics are not.

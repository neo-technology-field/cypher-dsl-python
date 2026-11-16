Compose query parts and unions
===============================

A statement is a sequence of clauses, and ``WITH`` ends one query part and starts the
next. Unions combine whole statements, and a statement built once can be stored, shared
and rendered repeatedly.

End a query part with WITH
--------------------------

Only the names a ``WITH`` projects are available to the clauses after it. A structured
projection item needs an alias, because the next part needs a name for the value:

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
An ordinary ``WITH`` filter can use both incoming variables and projected aliases, even
when the incoming variable is not passed on. With ``DISTINCT`` or an aggregation such as
``count``, the owning filter is restricted to projected names, and a filter cannot restore
a name an earlier ``WITH`` discarded.

Passing a plain variable through needs no alias:

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

    MATCH (p:Person) WITH p ORDER BY p.rating DESC LIMIT 1 RETURN p.display_name

``WITH`` carries the same ``distinct``, ``order_by``, ``skip`` and ``limit`` modifiers as
``RETURN``, so a query part can cut its rows before the next part reads them.

Combine statements with UNION
-----------------------------

``union`` completes and checks each builder and combines the results. ``UNION`` removes
duplicates, ``UNION ALL`` keeps them, and every branch ends in its own ``RETURN``:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param, union

    person = node("Person", name="p")
    movie = node("Movie", name="m")
    statement = union(
        match(person)
        .where(person["rating"] > param("min_rating", 4))
        .returning(person["display_name"].alias("who")),
        match(movie)
        .where(movie["released"] > param("since", 2000))
        .returning(movie["title"].alias("who")),
        all=True,
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)
      WHERE p.rating > $min_rating
    RETURN p.display_name AS who
    UNION ALL
    MATCH (m:Movie)
      WHERE m.released > $since
    RETURN m.title AS who

Branches must project the same width, and the projection names they declare must line up
by position. An incomplete builder is rejected when the union is built, not later at
render time.

Reuse and compare statements
----------------------------

Every builder call returns a new immutable value, so a statement built once can be kept
and rendered many times, including concurrently. ``build()`` completes the clauses
explicitly, and ``render`` accepts a builder, a ``Statement`` or a ``UnionStatement``:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param

    person = node("Person", name="p")
    statement = (
        match(person)
        .where(person["rating"] > param("min_rating"))
        .returning(person["display_name"])
        .build()
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    first = renderer.render(statement)
    second = renderer.render(statement)

    print(first.cypher == second.cypher)
    print(first.parameters is second.parameters)

.. code-block:: text

    True
    False

Expressions deliberately have no structural ``==``, because ``==`` builds a Cypher
comparison. Compare two statements with ``structurally_equal`` instead:

.. code-block:: python

    from cypher_dsl import match, node, structurally_equal

    person = node("Person", name="p")

    left = match(person).returning(person["display_name"]).build()
    right = (
        match(node("Person", name="p"))
        .returning(person["display_name"])
        .build()
    )

    print(structurally_equal(left, right))

.. code-block:: text

    True

Two structurally equal statements render the same text.

Read and filter data
====================

Reading starts with ``match`` or ``optional_match`` and ends with ``returning``. Filters
belong to the :ref:`clause <clause>` they constrain, conditions are
:ref:`expressions <expression>`, and projections can
compute values instead of only naming variables.

Match several patterns at once
------------------------------

``match`` accepts any number of comma-separated patterns:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node

    person = node("Person", name="p")
    movie = node("Movie", name="m")
    statement = match(person, movie).returning(person, movie)

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person), (m:Movie) RETURN p, m

A later ``match`` call extends the statement, and a ``match`` after an updating clause
needs a ``WITH`` boundary first, because Cypher starts a new query part there.

Keep rows that have no match
----------------------------

``optional_match`` keeps the incoming rows when its pattern finds nothing, and a filter
attached after it belongs to the optional match:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param

    person = node("Person", name="p")
    movie = node("Movie", name="m")
    statement = (
        match(person)
        .optional_match(person.relationship_to(movie, "ACTED_IN", name="r"))
        .where(movie["title"] == param("title"))
        .returning(person["display_name"], movie["title"])
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)
    OPTIONAL MATCH (p:Person)-[r:ACTED_IN]->(m:Movie)
      WHERE m.title = $title
    RETURN p.display_name, m.title

Build conditions with the DSL operators
---------------------------------------

Python cannot overload ``and``, ``or`` and ``not``, so conditions use ``&``, ``|`` and
``~``. Keep each comparison in its own parentheses, because Python binds ``&`` tighter
than ``>``:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param

    person = node("Person", name="p")
    statement = (
        match(person)
        .where(
            (person["rating"] > param("min_rating", 4.0))
            & (person["kind"] == "actor")
        )
        .returning(person["display_name"])
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)
      WHERE p.rating > $min_rating AND p.kind = 'actor'
    RETURN p.display_name

The renderer adds parentheses where Cypher precedence requires them, so the text follows
the Cypher precedence rules rather than the layout of the Python source.

Comparing an expression with ``None`` builds ``IS NULL`` and ``IS NOT NULL``:

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

For a membership test, ``in_`` accepts a :ref:`literal <literal>` collection, a parameter
or a list of
variables:

.. code-block:: python

    from cypher_dsl import (
        Configuration,
        Renderer,
        in_,
        lit,
        list_,
        match,
        name,
        node,
        param,
    )

    person = node("Person", name="p")
    renderer = Renderer.get(Configuration(server_version="5.26"))

    literal = (
        match(person)
        .where(in_(person["kind"], lit(["actor", "director"])))
        .returning(person)
    )
    bound = (
        match(person)
        .where(in_(person["kind"], param("kinds")))
        .returning(person)
    )
    variables = (
        match(person)
        .where(in_(person["uid"], list_(name("a"), name("b"))))
        .returning(person)
    )

    print(renderer.render(literal).cypher)
    print(renderer.render(bound).cypher)
    print(renderer.render(variables).cypher)

.. code-block:: cypher

    MATCH (p:Person) WHERE p.kind IN ['actor', 'director'] RETURN p
    MATCH (p:Person) WHERE p.kind IN $kinds RETURN p
    MATCH (p:Person) WHERE p.uid IN [a, b] RETURN p

String predicates build with ``starts_with``, ``ends_with`` and ``contains``. Each takes
the expression to test and the text to look for, which may be a :ref:`literal <literal>`,
a parameter or any expression:

.. code-block:: python

    from cypher_dsl import (
        Configuration,
        Renderer,
        contains,
        ends_with,
        match,
        node,
        param,
        starts_with,
    )

    person = node("Person", name="p")
    statement = (
        match(person)
        .where(starts_with(person["uid"], param("prefix")))
        .returning(person["uid"])
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) WHERE p.uid STARTS WITH $prefix RETURN p.uid

A parameter that already holds a boolean needs ``condition()``. The library does not infer
server-side types, so the caller states that the value is a predicate:

.. code-block:: python

    from cypher_dsl import (
        Configuration,
        Renderer,
        condition,
        match,
        node,
        param,
    )

    person = node("Person", name="p")
    statement = (
        match(person)
        .where(condition(param("active")))
        .returning(person)
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) WHERE $active RETURN p

Filter an UNWIND through WITH
-----------------------------

``WHERE`` belongs to ``MATCH`` or ``WITH``, so a predicate on unwound rows is added after
a ``WITH`` projects the row variable:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, name, param, unwind

    statement = (
        unwind(param("rows"), name("item"))
        .with_(name("item"))
        .where(name("item") != None)
        .returning(name("item"))
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    UNWIND $rows AS item WITH item WHERE item IS NOT NULL RETURN item

.. _functions:

Call functions
--------------

``fn`` calls a function by name, including dot-qualified names. Arguments accept literal
values and expressions, and a bare string argument stays a literal:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, fn, match, node

    person = node("Person", name="p")
    statement = (
        match(person)
        .returning(
            fn("coalesce", person["nickname"], "unknown"),
            fn("point.distance", person["here"], person["there"]),
        )
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)
    RETURN coalesce(p.nickname, 'unknown'), point.distance(p.here, p.there)

The library does not inspect installed procedures or reject names it does not recognise,
because an unknown name may be a user-defined function. ``count`` and ``element_id`` have
their own constructors, and ``count`` takes the explicit ``asterisk()``:

.. code-block:: python

    from cypher_dsl import (
        Configuration,
        Renderer,
        asterisk,
        count,
        element_id,
        match,
        node,
    )

    person = node("Person", name="p")
    statement = (
        match(person)
        .returning(
            count(asterisk()),
            count(person["email"], distinct=True),
            element_id(person),
        )
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) RETURN count(*), count(DISTINCT p.email), elementId(p)

``element_id`` always renders ``elementId(n)``. ``fn("id", ...)`` keeps whatever name the
caller supplied. For a function or operand the DSL does not model, :ref:`raw-expression`
renders trusted text unchanged.

.. _projection:

Project, alias and widen
------------------------

A projection lists expressions in order. A bare string is a :ref:`variable <variable>`
name, a string value
needs ``lit()``, and ``alias`` names a computed column:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param

    person = node("Person", name="p")
    statement = (
        match(person)
        .returning(
            "p",
            person["display_name"].alias("who"),
            param("requested_at"),
        )
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) RETURN p, p.display_name AS who, $requested_at

``asterisk()`` projects every name in scope, and ``returning`` can start a statement on
its own, which renders a standalone ``RETURN``:

.. code-block:: python

    from cypher_dsl import (
        Configuration,
        Renderer,
        asterisk,
        lit,
        match,
        node,
        returning,
    )

    person = node("Person", name="p")
    widened = match(person).returning(asterisk())
    constant = returning(lit(1))

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(widened).cypher)
    print(renderer.render(constant).cypher)

.. code-block:: cypher

    MATCH (p:Person) RETURN *
    RETURN 1

Deduplicate, order and paginate
-------------------------------

``distinct`` marks the projection, ``order_by`` appends ordering items, and one ``SKIP``
and one ``LIMIT`` position exist per projection:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, desc, match, node, param

    person = node("Person", name="p")
    statement = (
        match(person)
        .returning(person["display_name"], person["rating"])
        .distinct()
        .order_by(desc(person["rating"]))
        .skip(param("offset"))
        .limit(param("limit"))
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)
    RETURN DISTINCT p.display_name, p.rating
      ORDER BY p.rating DESC SKIP $offset LIMIT $limit

``DISTINCT`` restricts ordering and pagination to the projected result, so an ordering
item or filter that refers to a name the projection discards is rejected rather than
silently dropped. A bare expression in ``order_by`` sorts ascending without an ``ASC``
token. Use ``asc()`` when the token should appear. Pagination accepts a non-negative
integer literal or any expression whose runtime value the server decides, so a page size
is usually a parameter.

Compute values in the projection
--------------------------------

Arithmetic and string concatenation build expressions through the Python operators, and
``+`` concatenates strings in Cypher as well:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param

    person = node("Person", name="p")
    statement = match(person).returning(
        person["rating"] + 1,
        person["first_name"] + " " + person["last_name"],
        person["tags"][0],
        person["tags"][param("index")],
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)
    RETURN p.rating + 1, p.first_name + ' ' + p.last_name,
      p.tags[0], p.tags[$index]

A string index on an expression reads a static property. An integer or expression index
builds a subscript, which keeps a parameter a parameter instead of interpolating its text.

``map_`` builds a map value whose entries are expressions, which is how a projection
shapes a result object:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, lit, map_, match, node

    person = node("Person", name="p")
    statement = match(person).returning(
        map_({"uid": person["uid"], "kind": lit("person")})
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) RETURN {uid: p.uid, kind: 'person'}

Map keys are names and keep their insertion order. A bare string as a map value stays a
literal, so a variable value needs ``name()`` or a property read. See :doc:`parameters`
for how literal and map values are snapshotted.

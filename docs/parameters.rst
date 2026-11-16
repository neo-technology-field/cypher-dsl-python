Parameters and values
=====================

Request data belongs in a parameter. Escaping keeps a value from breaking the query
text, but it does not make inline request data desirable: a rendered string tends to end
up in a log, and its value defeats query-cache reuse. Put request data in ``param()``
and constants in ``lit()``.

Put request data in a parameter
-------------------------------

``param(name)`` adds ``$name`` to the text and leaves the value to your execution layer.
``param(name, value)`` adds ``$name`` and supplies the value. ``None`` is a real value,
so ``param(name, None)`` renders ``$name`` with a null value rather than becoming
unbound:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param

    person = node("Person", name="p")
    unbound = (
        match(person)
        .where(person["rating"] > param("min_rating"))
        .returning(person["display_name"])
    )
    bound = (
        match(person)
        .where(person["rating"] > param("min_rating", 4.5))
        .returning(person["display_name"])
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(unbound).cypher)
    print(renderer.render(unbound).parameters)
    print(renderer.render(unbound).unbound_parameters)
    print(renderer.render(bound).parameters)
    print(renderer.render(bound).unbound_parameters)

.. code-block:: text

    MATCH (p:Person) WHERE p.rating > $min_rating RETURN p.display_name
    {}
    frozenset({'min_rating'})
    {'min_rating': 4.5}
    frozenset()

The render reports an unbound name instead of inventing a value for it. Your execution
layer decides whether an unbound name is an error or is supplied from elsewhere. See
:doc:`running` for how the value reaches the query.

Bind one name once
------------------

Two different values for one parameter name in one render is a conflict, not a
last-write-wins merge:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param
    from cypher_dsl.errors import ConflictingParameterError

    person = node("Person", name="p")
    statement = (
        match(person)
        .where(param("limit", 1) == param("limit", 2))
        .returning(person)
    )

    try:
        Renderer.get(Configuration(server_version="5.26")).render(statement)
    except ConflictingParameterError as error:
        print(error)

.. code-block:: text

    Conflicting bindings for $limit

Two bindings count as the same only when their types match as well as their values:
``True`` and ``1`` are different bindings, and so are ``1`` and ``1.0``. An unbound use
of a name is resolved by a bound use of the same name in the same statement.

.. _literal:

Write a constant into the text
------------------------------

``lit()`` writes a Python value into the query text. Inline values keep their type:
``True``, ``None``, integers and finite floats render as themselves, and temporal values
use the constructor that matches their awareness:

.. code-block:: python

    from datetime import date, datetime, time, timedelta

    from cypher_dsl import Configuration, Renderer, lit, match, node

    person = node("Person", name="p")
    statement = match(person).returning(
        lit(date(1990, 5, 17)),
        lit(datetime(2026, 1, 2, 3, 4)),
        lit(time(9, 30)),
        lit(timedelta(hours=2)),
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)
    RETURN date('1990-05-17'), localdatetime('2026-01-02T03:04:00'),
      localtime('09:30:00'), duration('PT2H')

The value is snapshotted when the literal is built, so a list or mapping you change
afterwards does not change the rendered text:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, lit, match, node

    values = [1, 2]
    literal = lit(values)
    values.append(3)

    person = node("Person", name="p")
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(match(person).returning(literal)).cypher)

.. code-block:: cypher

    MATCH (p:Person) RETURN [1, 2]

Cyclic containers, non-string mapping keys and non-finite floats are rejected.

An inline ``bytes`` value is rejected, because Cypher has no byte-literal text. Bind it
with ``param()`` and pass it to the driver:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, lit, match, node

    person = node("Person", name="p")
    statement = match(person).returning(lit(b"raw"))

    try:
        Renderer.get(Configuration(server_version="5.26")).render(statement)
    except Exception as error:
        print(type(error).__name__)

.. code-block:: text

    InvalidLiteralError

Tell names and values apart
---------------------------

A bare string in a :ref:`projection <projection>` is a variable name. A string value
needs ``lit()``:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, lit, match, node

    person = node("Person", name="p")
    statement = match(person).returning("p", lit("p"))

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) RETURN p, 'p'

Function arguments and comparisons accept a bare literal or an
:ref:`expression <expression>`. A bare string
stays a literal value there, while an explicit ``name("p")`` or ``person.as_expression()``
supplies a :ref:`variable <variable>`:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, fn, match, node

    person = node("Person", name="p")
    statement = match(person).returning(
        fn("coalesce", person["nickname"], "unknown")
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) RETURN coalesce(p.nickname, 'unknown')

``lit()`` accepts Python values only. A variable or any other expression is rejected
with ``InvalidLiteralError``.

Carry a value the library cannot copy
-------------------------------------

Bound ``bytes`` pass through unchanged. The same applies to an object the library cannot
copy or inspect, such as a driver-owned spatial or temporal type:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param

    person = node("Person", name="p")
    statement = match(person).returning(param("blob", b"\x00\x01"))

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).parameters)

.. code-block:: text

    {'blob': b'\x00\x01'}

That object stays yours. The library does not copy it or read its fields, it must not
change while a render uses it, and two bindings of such objects count as the same only
when they are the same object.

How names are quoted
--------------------

A plain name stays bare. A name that is not a legal identifier, or that matches a Cypher
keyword, is backticked, and an embedded backtick is doubled:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node

    person = node("Person", name="p")
    statement = match(person).returning(person["name"])
    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) RETURN p.`name`

``Configuration(server_version="5.26", always_escape_names=True)`` quotes every
identifier instead of only the ones that need it.

A parameter name follows the same rules, with one exception. A name that matches a
Cypher keyword is not quoted after ``$``, because the ``$`` already introduces the name:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param

    person = node("Person", name="p")
    default = Renderer.get(Configuration(server_version="5.26"))
    statement = match(person).returning(param("request value", 1))
    print(default.render(statement).cypher)

    forced = Renderer.get(
        Configuration(server_version="5.26", always_escape_names=True)
    )
    print(forced.render(match(person).returning(param("value", 1))).cypher)

.. code-block:: cypher

    MATCH (p:Person) RETURN $`request value`
    MATCH (`p`:`Person`) RETURN $`value`

So ``$value`` stays bare by default because ``value`` is a keyword and the ``$`` already
introduces the name, while ``request value`` is backticked after ``$`` because it is not
a legal bare identifier.

What the renderer will not do
-----------------------------

This release does not convert literals into parameters. Every parameter is explicit, so
the rendered text and the parameter dictionary are predictable. Query-cache reuse is
therefore your decision rather than a hidden rewrite.

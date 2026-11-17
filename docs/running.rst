Render and run the query
========================

Rendering turns a statement into query text and parameter containers. It never opens a
connection: passing the result to a driver is the application's job, and the library
imposes nothing on how that happens.

Get a renderer for your target
------------------------------

``Renderer.get`` validates one configuration and returns a renderer that holds no
per-render state, so it can be stored in a module global and shared between threads:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node

    renderer = Renderer.get(Configuration(server_version="5.26"))

    person = node("Person", name="p")
    statement = match(person).returning(person["display_name"])

    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) RETURN p.display_name

``render`` accepts a builder, a ``Statement`` or a ``UnionStatement``. A builder is
checked and completed when it is rendered. The default configuration renders each
statement on one line; :ref:`pretty-print` shows the multi-line layout. See
:doc:`targets` for how ``server_version`` and the language selection are chosen.

Read the render result
----------------------

A ``Rendered`` carries the complete query text, a fresh parameter dictionary and a
frozenset of unbound parameter names:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param

    person = node("Person", name="p")
    statement = (
        match(person)
        .where(person["email"] == param("email"))
        .returning(person["display_name"])
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    rendered = renderer.render(statement)

    print(rendered.cypher)
    print(rendered.parameters)
    print(sorted(rendered.unbound_parameters))
    print(rendered)

.. code-block:: text

    MATCH (p:Person) WHERE p.email = $email RETURN p.display_name
    {}
    ['email']
    MATCH (p:Person) WHERE p.email = $email RETURN p.display_name

Printing a result prints the query text. Every render returns its own parameter
dictionary, so changing one result's dictionary leaves the statement and other results
alone. See :doc:`parameters` for how bindings are compared.

Supply the unbound values at execution
--------------------------------------

A render reports what the caller still has to supply instead of inventing a value, so the
execution layer completes the parameter dictionary:

.. code-block:: python

    from neo4j import GraphDatabase

    from cypher_dsl import Configuration, Renderer, match, node, param

    renderer = Renderer.get(Configuration(server_version="5.26"))

    person = node("Person", name="p")
    statement = (
        match(person)
        .where(person["email"] == param("email"))
        .returning(person["display_name"])
    )

    rendered = renderer.render(statement)
    parameters = {**rendered.parameters, "email": "ada@example.com"}

    with GraphDatabase.driver(
        "neo4j://localhost:7687", auth=("neo4j", "password")
    ) as driver:
        with driver.session(database="neo4j") as session:
            rows = session.run(rendered.cypher, parameters).data()

The driver is not a dependency of this library. Any client that accepts query text plus a
parameter mapping works, because a ``Rendered`` is exactly those two things.

Log the text, not the values
----------------------------

The rendered text contains placeholders instead of request data, so logging it cannot
leak a value. The values live in the parameter dictionary and stay under the caller's
control:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param

    person = node("Person", name="p")
    statement = (
        match(person)
        .where(person["email"] == param("email", "ada@example.com"))
        .returning(person["display_name"])
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    rendered = renderer.render(statement)

    print(f"slow query: {rendered.cypher}")
    print(f"binding count: {len(rendered.parameters)}")

.. code-block:: text

    slow query: MATCH (p:Person) WHERE p.email = $email RETURN p.display_name
    binding count: 1

Test the queries your application builds
-----------------------------------------

A query built by application code is a value, so a test asserts it without a database.
Assert the complete text, and assert that the names the request layer must supply are
exactly the unbound ones:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param

    renderer = Renderer.get(Configuration(server_version="5.26"))


    def people_above(min_rating: float):
        person = node("Person", name="p")
        statement = (
            match(person)
            .where(person["rating"] > param("min_rating"))
            .returning(person["display_name"])
        )
        return renderer.render(statement)


    rendered = people_above(4.0)
    assert rendered.cypher == (
        "MATCH (p:Person) WHERE p.rating > $min_rating RETURN p.display_name"
    )
    assert rendered.unbound_parameters == frozenset({"min_rating"})
    print(rendered.cypher)

.. code-block:: cypher

    MATCH (p:Person) WHERE p.rating > $min_rating RETURN p.display_name

The unbound assertion is the practical one. A name the request layer does not supply
fails in the test instead of at the first execution, and a name it stopped supplying
disappears from the assertion and forces a decision.

Building and rendering run in milliseconds, so a suite can cover every query shape the
application issues without a server. Keep one thin layer that executes the rendered text
against a database you own and asserts the data there once, rather than running the whole
suite against a server.

A rendering test does not prove that a server accepts the statement. Server-side
semantics, missing labels and property types are outside this library.

Catch the library's failures
----------------------------

Every construction and rendering failure derives from ``DslError``, so one except clause
covers the library without catching unrelated Python exceptions:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node
    from cypher_dsl.errors import DslError

    renderer = Renderer.get(Configuration(server_version="5.26"))

    try:
        renderer.render(match(node("Person", name="p")))
    except DslError as error:
        print(type(error).__name__)
        print(error)

.. code-block:: text

    DslError
    A statement must end with a RETURN clause or a write clause. A read that
      stops at MATCH is incomplete.

The specific classes and when each is raised are listed in :doc:`errors`.

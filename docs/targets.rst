Choose a target
===============

``server_version`` is required. It declares the Neo4j release the rendered text will run
on, and the declared release decides which syntax is accepted. The library never probes a
server. Neo4j 5.26 LTS is the minimum supported release. Earlier 5.x releases and 4.x are
unsupported.

- Use a two- or three-component string, such as ``"5.26"`` or ``"2026.10.2"``.
- Releases are compared numerically, so 5.26 is newer than 5.9. Patch components are retained.
- Missing, malformed or unsupported releases fail when ``Configuration`` is built.
- Declaring a release does not verify the actual server or its database-default language.

Let each statement select its language
--------------------------------------

``Language.AUTO`` is the default. It selects a prefix from the statement's syntax requirements,
not from the newest language the declared server offers:

- A statement with no language floor renders without a prefix.
- A release-only requirement does not add a prefix.
- A requirement with a Cypher 25 language floor selects ``CYPHER 25`` for that statement.

The same renderer can therefore render an ordinary statement unprefixed and select a language
for another statement. Selecting a language never bypasses a release floor.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node

    person = node("Person", name="p")
    statement = match(person).returning(person)
    renderer = Renderer.get(Configuration(server_version="2026.10"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) RETURN p

Pin the language when the text must name it
-------------------------------------------

``Language.CYPHER_5`` and ``Language.CYPHER_25`` always render their prefix. A pinned
language that cannot express a statement's required syntax is refused. Pinning makes the
language explicit at the cost of restricting which syntax the statement can use.

.. code-block:: python

    from cypher_dsl import Configuration, Language, Renderer, match, node

    person = node("Person", name="p")
    statement = match(person).returning(person)
    for language in (Language.CYPHER_5, Language.CYPHER_25):
        configuration = Configuration(
        server_version="2026.10.2", language=language
    )
        print(Renderer.get(configuration).render(statement).cypher)

.. code-block:: cypher

    CYPHER 5 MATCH (p:Person) RETURN p
    CYPHER 25 MATCH (p:Person) RETURN p

The prefixes also have minimum releases, separate from the syntax floors above:

.. list-table::
   :header-rows: 1

   * - Selection
     - Prefix
     - Minimum Neo4j release
   * - ``Language.CYPHER_5``
     - ``CYPHER 5``
     - 5.21
   * - ``Language.CYPHER_25``
     - ``CYPHER 25``
     - 2025.06

- The `Cypher additions manual
  <https://neo4j.com/docs/cypher-manual/current/deprecations-additions-removals-compatibility/#cypher-deprecations-additions-removals-2025.06>`_
  states that selecting ``CYPHER 5`` was introduced in Neo4j 5.21, below the supported
  minimum, so every supported target accepts that prefix and no floor enforces it. The
  `tagged 5.21 parser test
  <https://github.com/neo4j/neo4j/blob/5.21/community/cypher/cypher/src/test/scala/org/neo4j/cypher/internal/PreParserTest.scala>`_
  accepts ``CYPHER 5 RETURN 42``.
- The `Select Cypher version manual <https://neo4j.com/docs/cypher-manual/current/queries/select-version/>`_
  requires Neo4j 2025.06 or later for ``CYPHER 25``. This is the one language floor the
  library enforces at construction. Its 2025.06 introduction does not date the older
  ``CYPHER 5`` prefix.

An unavailable language is rejected when the configuration is built:

.. code-block:: python

    from cypher_dsl import Configuration, Language
    from cypher_dsl.errors import UnsupportedFeatureError

    try:
        Configuration(server_version="5.26.0", language=Language.CYPHER_25)
    except UnsupportedFeatureError as error:
        print(error)

.. code-block:: text

    CYPHER 25 requires Neo4j 2025.06 or later, but server_version is 5.26.0.
    Select a compatible release or language.

Suppress the prefix only when the database default is controlled
----------------------------------------------------------------

``Language.NONE`` never renders a language prefix. It still checks every release floor,
but leaves the language to the database default. A release that supports
Cypher 25 can still have Cypher 5 as its database default. Suppressing a required prefix
then produces text that the configured default cannot parse. The library does not check
that default, so the application must control it.

.. code-block:: python

    from cypher_dsl import Configuration, Language, Renderer, match, node

    person = node("Person", name="p")
    configuration = Configuration(
        server_version="2026.10", language=Language.NONE
    )
    renderer = Renderer.get(configuration)
    print(renderer.render(match(person).returning(person)).cypher)

.. code-block:: cypher

    MATCH (p:Person) RETURN p

Quote every name when output should not depend on context
---------------------------------------------------------

``Configuration(server_version="5.26", always_escape_names=True)`` backticks every
identifier. The default quotes only names that need it, which keeps output close to
hand-written Cypher. Forced escaping produces valid but noisy text, and upstream fixtures
that use it expect the extra backticks.

.. _pretty-print:

Render statements for reading
-----------------------------

``Configuration(pretty_print=True)`` renders a statement as multi-line text for a person
to read, at a fixed width of 120 columns. The default renders one line, which stays
cacheable and log-friendly.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, desc, match, node, param

    person = node("Person", name="p")
    statement = (
        match(person)
        .where(
            (person["rating"] > param("min_rating"))
            & (person["email"] == param("email"))
        )
        .returning(person["display_name"], person["rating"])
        .order_by(desc(person["rating"]))
        .skip(param("offset"))
        .limit(param("limit"))
    )
    renderer = Renderer.get(Configuration(server_version="5.26", pretty_print=True))
    print(renderer.render(statement).cypher)

.. code-block:: text

    MATCH (p:Person)
      WHERE p.rating > $min_rating AND p.email = $email
    RETURN p.display_name, p.rating
      ORDER BY p.rating DESC SKIP $offset LIMIT $limit

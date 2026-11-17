Which errors the library raises
===============================

Every construction and rendering failure derives from ``DslError``, so callers can catch
the library's own failures without catching unrelated Python exceptions. Messages name the
construct that failed and, where the choice exists, the supported alternative.

The classes
-----------

.. list-table::
   :header-rows: 1

   * - Class
     - Raised when
   * - ``DslError``
     - A grammar or shape rule is violated directly, for example a projection without an
       item, a filter with no clause to own it, or a read that stops at ``MATCH``.
   * - ``UnsupportedFeatureError``
     - A requested construct is outside the implemented surface: a release or language
       floor that the declared target does not meet, or a value kind with no rendering
       rule.
   * - ``InvalidClauseOrderError``
     - Clauses form a sequence Cypher does not accept, such as ``WHERE`` after ``RETURN``
       or a second ``RETURN`` in one statement.
   * - ``ConflictingParameterError``
     - One parameter name carries two different bindings in a single render.
   * - ``InvalidIdentifierError``
     - A name cannot be rendered as a quoted identifier, for example an empty name, a
       control character, or an encoded escape that Cypher would read as a backtick.
   * - ``EmptyPatternError``
     - A grammar position requires at least one pattern or item and received none.
   * - ``InvalidLiteralError``
     - A Python value cannot be written into the query text as a literal, for example a
       non-finite float, a cyclic container or inline ``bytes``.

Where each family comes from
----------------------------

Construction and validation raise while the statement is being built, so a malformed
statement fails before rendering:

.. code-block:: python

    from cypher_dsl import match, node, returning
    from cypher_dsl.errors import InvalidClauseOrderError

    person = node("Person", name="p")

    try:
        match(person).returning(person).where(person["rating"] > 1)
    except InvalidClauseOrderError as error:
        print(error)

.. code-block:: text

    WHERE must precede RETURN in a statement.

Target checks raise when the configuration or the render runs,
so an unavailable language or syntax the declared release cannot parse fails there:

.. code-block:: python

    from cypher_dsl import Configuration, Language
    from cypher_dsl.errors import UnsupportedFeatureError

    try:
        Configuration(server_version="5.26", language=Language.CYPHER_25)
    except UnsupportedFeatureError as error:
        print(error)

.. code-block:: text

    CYPHER 25 requires Neo4j 2025.06 or later, but server_version is 5.26.
    Select a compatible release or language.

Binding conflicts are found when the statement is rendered, because a bound and an
unbound use of one name only meet there. See :doc:`parameters` for the binding rules and
:doc:`targets` for the release and language floors.

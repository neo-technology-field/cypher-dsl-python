Call procedures
===============

Cypher has two ``CALL`` forms. The subquery form runs a finalised statement in its own
scope and is documented on :doc:`subqueries`; the procedure form invokes a stored
procedure and is documented here. A procedure call holds a procedure name, its arguments
and the output columns it keeps, and the library checks it with the same scope rules as
the rest of the statement.

.. _procedure-call:

Call a procedure and read its output
------------------------------------

``call_procedure`` starts a statement on its own or continues one that already holds
reading clauses. The procedure name is one dot-qualified string, such as
``dbms.checkConfigValue``, split on dots at construction. The arguments are
:ref:`expressions <expression>`: literals, parameters, variable names and any other
expression, with a bare string staying a literal value, the same rule ``fn`` follows
under :ref:`functions`. The parentheses around the argument list always render, including
the empty list of a procedure that takes no arguments.

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

``yielding`` names the output columns the call keeps, and the clause after the call reads
them under those names.

.. _standalone-procedure-call:

Call a procedure on its own
---------------------------

A call without yield items finalises on its own: ``build()`` completes the statement the
way it completes a write clause, and rendering accepts the builder directly. The server
returns every column the procedure produces by default.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, call_procedure

    statement = call_procedure("db.labels")

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    CALL db.labels()

The library does not know procedure signatures. It cannot name the output columns of a
standalone call, so it checks nothing about them: the server decides which columns the
result holds and what they mean.

.. _procedure-yield:

Yield and rename output columns
-------------------------------

A standalone call leaves the columns to the server. Inside a larger query the kept
columns must be named explicitly, one yield item per column. ``yielding`` accepts a bare
name, a variable, or a variable under one alias: ``name("versions").alias("installed")``
renames the column ``versions`` to ``installed``. The alias, or the plain name when there
is no alias, is the binding the clauses after the call see. Repeated ``yielding`` calls
append to the same list.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, call_procedure, name

    statement = (
        call_procedure("dbms.components")
        .yielding("edition", name("versions").alias("installed"))
        .returning(name("installed"))
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    CALL dbms.components() YIELD edition, versions AS installed RETURN installed

A yield item that binds a name the query already holds is rejected, because the call would
redeclare it. Alias the column to a fresh name instead. Two items that bind the same name
are rejected as well.

.. _procedure-filter:

Filter the yielded rows
-----------------------

``where`` after the yield attaches the filter to the ``YIELD``: it renders after the yield
items and keeps only the rows that satisfy it.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, call_procedure, lit, name

    statement = (
        call_procedure("db.labels")
        .yielding("label")
        .where(name("label") == lit("Person"))
        .returning(name("label"))
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    CALL db.labels() YIELD `label` WHERE `label` = 'Person' RETURN `label`

``label`` is a reserved word, so the renderer quotes it. The default escaping quotes only
the names that need it; :doc:`targets` states the rule.

The predicate sees the names the outer query holds and the names the call yields:

.. code-block:: python

    from cypher_dsl import (
        Configuration,
        Renderer,
        call_procedure,
        match,
        name,
        node,
    )

    person = node("Person", name="p")
    statement = (
        match(person)
        .call_procedure("db.labels")
        .yielding("label")
        .where(name("label") != person["kind"])
        .returning(name("label"))
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)
    CALL db.labels() YIELD `label`
      WHERE `label` <> p.kind
    RETURN `label`

A name that the outer query does not hold and the call does not yield is rejected.
Repeated ``where`` calls combine with ``AND``, because the call holds one filter position
after ``YIELD``:

.. code-block:: python

    from cypher_dsl import (
        Configuration,
        Renderer,
        call_procedure,
        lit,
        name,
        param,
    )

    statement = (
        call_procedure(
            "dbms.checkConfigValue", param("setting"), param("expected")
        )
        .yielding(name("valid"), name("actual").alias("observed"))
        .where(name("valid") == lit(True))
        .where(name("observed") != None)
        .returning(name("valid"), name("observed"))
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    CALL dbms.checkConfigValue($setting, $expected)
      YIELD valid, actual AS observed
      WHERE valid = true AND observed IS NOT NULL
    RETURN valid, observed

.. _optional-procedure-call:

Keep rows the procedure has no output for
-----------------------------------------

``optional_call_procedure`` renders ``OPTIONAL CALL``. A row the procedure produces no
output for survives with ``null`` bindings for the yielded names, the same way
``OPTIONAL MATCH`` keeps a row without a match.

.. code-block:: python

    from cypher_dsl import (
        Configuration,
        Renderer,
        match,
        name,
        node,
        optional_call_procedure,
    )

    person = node("Person", name="p")
    statement = (
        match(person)
        .optional_call_procedure("apoc.neighbors.tohop", name("p"), "KNOWS>", 1)
        .yielding("node")
        .returning(person["display_name"], name("node"))
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)
    OPTIONAL CALL apoc.neighbors.tohop(p, 'KNOWS>', 1) YIELD `node`
    RETURN p.display_name, `node`

A person with no ``KNOWS`` neighbour survives the call with a null ``node`` binding.
``OPTIONAL CALL`` of a procedure arrived in Neo4j 5.24, below this library's 5.26
minimum, so every supported release accepts it.

.. _procedure-call-position:

Where a procedure call may appear
---------------------------------

A procedure call is a reading clause, like ``MATCH`` and ``UNWIND``. It follows another
reading clause freely, and after an updating clause it needs a ``WITH`` boundary first,
because Cypher starts a new :ref:`query part <query-part>` there.

.. code-block:: python

    from cypher_dsl import (
        Configuration,
        Renderer,
        assign,
        call_procedure,
        match,
        node,
    )

    person = node("Person", name="p")
    statement = (
        match(person)
        .set_(assign(person["flags"], "seen"))
        .with_(person)
        .call_procedure("db.labels")
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) SET p.flags = 'seen'
    WITH p CALL db.labels()

A call without yield items may end a statement, the way a write clause may. A call with
yield items must feed a following clause: ``RETURN``, ``WITH`` or any other clause that
consumes the yielded names.

What is not available
---------------------

- No ``YIELD *``. Every kept column is named explicitly.
- No parenthesis omission. A procedure that takes no arguments still renders the empty
  argument list.
- No ``SHOW PROCEDURES`` or the other catalogue commands.

Call subqueries
===============

A ``CALL`` subquery runs a finalised statement once for every row the outer query holds
at that point, in its own scope. This library always renders the variable scope clause,
so outer variables enter the body only through it. The names the body returns become
available to the clauses after the call.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, name, node

    person = node("Person", name="p")
    movie = node("Movie", name="m")
    body = (
        match(person.relationship_to(movie, "ACTED_IN"))
        .returning(movie["title"].alias("title"))
        .build()
    )
    statement = match(person).call(body, imports=("p",)).returning(name("title"))

    renderer = Renderer.get(Configuration(server_version="5.26", pretty_print=True))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)
    CALL (p) {
      MATCH (p)-[:ACTED_IN]->(m:Movie) RETURN m.title AS title
    }
    RETURN title

The body is a complete statement. It is built with the same builders, checked by the same
rules and finalised before the call holds it. Reusing the imported ``p`` in a pattern is
a reference to the bound node, not a new declaration, which is what lets the body extend
a traversal from the outer row.

A body that ends in ``RETURN`` is a returning subquery: its output rows become the rows
after the call. A body that ends in a write clause is a unit subquery: it changes the
graph without changing the number of rows.

Import all, some or no variables
--------------------------------

``imports`` names the outer variables the body receives. ``import_all=True`` renders
``(*)`` and passes every outer variable in. An omitted ``imports`` renders ``()`` and
passes nothing, so the body is independent of the outer row.

.. code-block:: python

    from cypher_dsl import call, match, name, node

    person = node("Person", name="p")
    team = node("Team", name="t")
    player = node("Player", name="pl")
    body = match(player).returning(player["name"].alias("player")).build()

    every = match(person, team)
                    .call(body, import_all=True)
                    .returning(name("player"))
    none = call(body).returning(name("player"))

.. code-block:: cypher

    MATCH (p:Person), (t:Team)
    CALL (*) {
      MATCH (pl:Player)
      RETURN pl.`name` AS player
    }
    RETURN player
    CALL () {
      MATCH (pl:Player)
      RETURN pl.`name` AS player
    }
    RETURN player

The imports are plain variable names. Aliases are not part of the scope clause, and an
import must be bound by the clauses in front of the call.

Keep rows the subquery drops
----------------------------

``optional_call`` renders ``OPTIONAL CALL``. When the body produces no rows for an
incoming row, that row survives with ``null`` bindings for the returned names, the same
way ``OPTIONAL MATCH`` keeps a row without a match.

.. code-block:: python

    from cypher_dsl import match, name, node

    person = node("Person", name="p")
    movie = node("Movie", name="m")
    body = (
        match(person.relationship_to(movie, "ACTED_IN"))
        .returning(movie["title"].alias("title"))
        .build()
    )
    statement = match(person)
                   .optional_call(body, imports=("p",))
                   .returning(name("title"))

.. code-block:: cypher

    MATCH (p:Person)
    OPTIONAL CALL (p) {
      MATCH (p)-[:ACTED_IN]->(m:Movie)
      RETURN m.title AS title
    }
    RETURN title

Write in batches
----------------

``in_transactions`` appends ``IN TRANSACTIONS`` and runs the body in separate inner
transactions. It defaults to ``False`` and renders no modifier. Pass ``True`` for the
bare modifier, or a positive integer literal, a parameter or an expression to set the
input rows per transaction with ``OF ... ROWS``. The server uses 1000 rows when the
modifier carries no row count.

Neo4j requires the row count to evaluate to a positive integer without referring to
query variables or reading the graph. A row count that breaks either rule can fail
semantic checking before execution, so a statement that renders is not proof that a
server accepts it. The transactions manual linked below states both constraints.

.. code-block:: python

    from cypher_dsl import create, fn, name, node, unwind

    body = create(node("Clone", properties={"uid": name("item")})).build()
    statement = (
        unwind(fn("range", 1, 100_000), name("item"))
        .call(body, imports=("item",), in_transactions=5_000)
        .returning(name("item"))
    )

.. code-block:: cypher

    UNWIND range(1, 100000) AS item
    CALL (item) {
      CREATE (:Clone {uid: item})
    } IN TRANSACTIONS OF 5000 ROWS
    RETURN item

The example writes 100,000 clones in twenty transactions of 5,000 rows.

A server runs ``IN TRANSACTIONS`` only in an implicit transaction, so driver users send
these statements outside an explicit transaction. That is an execution concern: the
library renders the text and checks nothing about the transaction it will run in.

The builder has no concurrency, error-handling or status options. Full server semantics,
including what a failure rolls back, are not certified by this library. The
`CALL subqueries in transactions manual
<https://neo4j.com/docs/cypher-manual/5/subqueries/subqueries-in-transactions/>`_ states
the server rules.

Process a UNION
---------------

A union is a finalised statement, so it can be the body of a call. This is how a query
keeps processing rows after a ``UNION``.

.. code-block:: python

    from cypher_dsl import call, match, name, node, union

    person = node("Person", name="p")
    movie = node("Movie", name="m")
    left = match(person).returning(person["uid"].alias("uid"))
    right = match(movie).returning(movie["uid"].alias("uid"))
    statement = call(union(left, right)).returning(name("uid"))

.. code-block:: cypher

    CALL () {
      MATCH (p:Person) RETURN p.uid AS uid
      UNION
      MATCH (m:Movie) RETURN m.uid AS uid
    }
    RETURN uid

What the library checks
-----------------------

- An import must name a variable the clauses in front of the call bind.
- Named imports and ``import_all`` cannot be combined.
- An imported name cannot be rebound by an ``UNWIND`` target or a ``WITH`` expression.
  Passing an imported variable through a ``WITH`` unchanged is allowed. A ``MATCH``
  pattern can reference a retained import with different labels or properties. These
  filter the bound node rather than declare a new one.

  An exact restatement renders as the bare variable. A differing declaration keeps its
  labels as a filter, and a label filter reads clearer as ``WHERE p:Manager`` built
  with :ref:`has_label <label-expression-predicate>`.
- ``CREATE`` and ``MERGE`` can reference an imported node as a relationship endpoint
  when its declaration matches the bound node. They cannot redeclare it as a standalone
  node. Reference endpoints render only the variable, without labels or properties.
- The body cannot reference an outer name it does not import. Write-node properties
  suppressed for a reference endpoint do not count as body references. Declared-node
  properties, relationship properties and ``MATCH`` filters are still checked.
- A returning body cannot bind a name the outer query already holds. Rename the returned
  value instead.
- A statement may end with a subquery call only when the body is a unit subquery. A
  returning body needs a ``RETURN`` or another clause after the call.
- A call counts as a reading clause: after an updating clause in the same query part it
  needs a ``WITH`` boundary first.

One rule is stricter than the server's. Neo4j keeps imported variables available through
every ``WITH`` inside the subquery, but this library applies its ordinary scope model to
the body, so a ``WITH`` that drops an imported name also drops it for the rest of the
body. Keep the import in the inner ``WITH`` projection when the body needs it later.

Test whether a subquery matches
-------------------------------

``exists`` builds an ``EXISTS { ... }`` subquery expression. Its value is a predicate, so
it filters in ``WHERE``, projects in ``RETURN`` and combines with ``&``, ``|`` and ``~``.
Unlike a ``CALL`` subquery, the body reads the enclosing scope without a scope clause, so
an outer name is visible inside the body as it is outside. The body must be a read query,
and the names it binds stay inside the expression. For a chain that only references
names the outer query already binds, :ref:`path pattern expressions
<path-pattern-expression>` are the concise form without a body.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, exists, match, node, param

    person = node("Person", name="p")
    dog = node("Dog", name="d")
    walked = match(person.relationship_to(dog, "HAS_DOG")).where(
        dog["name"] == param("dog_name")
    )
    statement = match(person).where(exists(walked)).returning(person["name"])

    renderer = Renderer.get(Configuration(server_version="5.26", pretty_print=True))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)
      WHERE EXISTS {
        MATCH (p)-[:HAS_DOG]->(d:Dog) WHERE d.`name` = $dog_name
      }
    RETURN p.`name`

A pattern element is accepted where the body is one pattern, and the rendered text names
the ``MATCH`` keyword. A final ``RETURN`` in the body is optional and its columns are
discarded: ``EXISTS`` tests only whether the body produces a row. A union body follows
the rule the ``UNION`` builder applies to branches.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, exists, match, node

    person = node("Person", name="p")
    keeps_dog = exists(person.relationship_to(node("Dog"), "HAS_DOG"))
    statement = match(person).returning(person["name"], keeps_dog.alias("keeps_dog"))

    renderer = Renderer.get(Configuration(server_version="5.26", pretty_print=True))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)
    RETURN p.`name`, EXISTS {
      MATCH (p)-[:HAS_DOG]->(:Dog)
    } AS keeps_dog

Two limits follow from the scope model. A body ``WITH`` that drops an enclosing name does
not keep that name visible afterwards, so carry the variable through that ``WITH`` or let
a body pattern re-declare it. Shadowing is not rejected here, only by the server: a body
``WITH`` that binds an enclosing name to a new value builds and renders, and the server
rejects the statement.

Four checks apply to this construct:

- The body must not write. ``CREATE``, ``MERGE``, ``SET``, ``REMOVE``, ``DELETE`` and
  ``IN TRANSACTIONS`` are rejected, including inside a nested call body.
- A union body needs ``RETURN`` in every branch or in none.
- The names the body binds do not become available outside the expression.
- The body reads the names it binds itself and the names the enclosing query has bound.
  Where the library knows the enclosing clause's names, a name it has not bound gets the
  usual ``not in scope`` rejection, which names the offender.

.. _count-subquery:

Count the rows of a subquery
----------------------------

``count_subquery`` builds a ``COUNT { ... }`` subquery expression. Its value is an
integer, so it compares in ``WHERE``, projects in ``RETURN`` and assigns in ``SET``.
The body is a read query that sees the enclosing scope without a scope clause, and a
final ``RETURN`` is optional: its columns are discarded, because the value is the
number of rows.

.. code-block:: python

    from cypher_dsl import (
        Configuration,
        Renderer,
        count_subquery,
        lit,
        match,
        node,
    )

    person = node("Person", name="p")
    walked = match(person.relationship_to(node("Dog"), "HAS_DOG"))
    statement = (
        match(person)
        .where(count_subquery(walked) > lit(1))
        .returning(person["name"])
    )

    renderer = Renderer.get(Configuration(server_version="5.26", pretty_print=True))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)
      WHERE COUNT {
        MATCH (p)-[:HAS_DOG]->(:Dog)
      } > 1
    RETURN p.`name`

A pattern element is accepted where the body is one pattern, and the rendered text
names the ``MATCH`` keyword, as ``exists`` does. The manual's form without the keyword
is not produced. A union body follows the rule the ``UNION`` builder applies to
branches. The scope rules and limits are the ones ``EXISTS`` follows above.

.. _collect-subquery:

Collect a subquery into a list
------------------------------

``collect_subquery`` builds a ``COLLECT { ... }`` subquery expression. Its value is a
list with one element per body row. Every branch must end in a ``RETURN`` projecting
exactly one column, so a body without one is rejected when the expression is built.
The body sees the enclosing scope without a scope clause, like the other subquery
expressions.

.. code-block:: python

    from cypher_dsl import (
        Configuration,
        Renderer,
        collect_subquery,
        in_,
        lit,
        match,
        node,
    )

    person = node("Person", name="p")
    dog = node("Dog", name="d")
    dogs = match(person.relationship_to(dog, "HAS_DOG")).returning(dog["name"])
    statement = (
        match(person)
        .where(in_(lit("Ozzy"), collect_subquery(dogs)))
        .returning(person["name"])
    )

    renderer = Renderer.get(Configuration(server_version="5.26", pretty_print=True))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)
      WHERE 'Ozzy' IN COLLECT {
        MATCH (p)-[:HAS_DOG]->(d:Dog) RETURN d.`name`
      }
    RETURN p.`name`

Three checks apply to both constructs, and ``COLLECT`` adds a fourth:

- The body must not write. ``CREATE``, ``MERGE``, ``SET``, ``REMOVE``, ``DELETE`` and
  ``IN TRANSACTIONS`` are rejected, including inside a nested call body.
- The body reads the names it binds itself and the names the enclosing query has
  bound, without imports. Where the library knows the enclosing clause's names, a name
  it has not bound gets the usual ``not in scope`` rejection.
- The names the body binds do not become available outside the expression.
- A ``COLLECT`` body needs ``RETURN`` in every branch, with exactly one column;
  ``RETURN *`` is rejected because its column count depends on the scope.

Calling procedures
------------------

A procedure call is a whole clause built with ``call_procedure``, not a subquery: it
invokes a stored procedure by name and binds the columns it yields. :doc:`procedures`
documents the call, its :ref:`yield items <procedure-yield>` and the filter after them.

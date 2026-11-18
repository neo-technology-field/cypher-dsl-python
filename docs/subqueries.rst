Call subqueries
===============

A ``CALL`` subquery runs a finalised statement once for every row the outer query holds
at that point, in its own scope. This library always renders the variable scope clause,
so outer variables enter the body only through it. The names the body returns become
available to the clauses after the call.

.. code-block:: python

    from cypher_dsl import match, name, node

    person = node("Person", name="p")
    movie = node("Movie", name="m")
    body = (
        match(person.relationship_to(movie, "ACTED_IN"))
        .returning(movie["title"].alias("title"))
        .build()
    )
    statement = match(person).call(body, imports=("p",)).returning(name("title"))

.. code-block:: cypher

    MATCH (p:Person)
    CALL (p) {
      MATCH (p:Person)-[:ACTED_IN]->(m:Movie)
      RETURN m.title AS title
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
      MATCH (p:Person)-[:ACTED_IN]->(m:Movie)
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


Calling procedures
------------------

A procedure call is a whole clause built with ``call_procedure``, not a subquery: it
invokes a stored procedure by name and binds the columns it yields. :doc:`procedures`
documents the call, its :ref:`yield items <procedure-yield>` and the filter after them.

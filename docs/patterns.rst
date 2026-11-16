Describe nodes and relationships
================================

.. _variable:

``node()`` builds a node pattern, and the three relationship factories connect patterns
into a chain. The variable is the pattern's identity: other code refers to the node
through it, and a write clause can reuse an already-bound pattern as a relationship
endpoint.

.. _expression:

An expression is anything that can stand where Cypher expects a value: a variable, a
property read such as ``person["display_name"]``, a parameter, a
:ref:`literal <literal>` or a function call. Expressions appear in filters, projections,
function arguments and property maps. A pattern is not itself an expression. A named
pattern stands in for its variable wherever one is needed, and an anonymous pattern has
nothing to stand in.

Build a node pattern
--------------------

``node()`` takes one primary label, an optional variable and an optional property map:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param

    person = node("Person", name="p", properties={"email": param("email")})
    statement = match(person).returning(person["display_name"])

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person {email: $email}) RETURN p.display_name

A label is required, because this library has no unlabelled node pattern. The variable is
optional. ``node("Movie")`` renders ``(:Movie)``, and using it where an expression is
expected fails instead of inventing a name:

.. code-block:: python

    from cypher_dsl import node
    from cypher_dsl.errors import DslError

    try:
        node("Movie").as_expression()
    except DslError as error:
        print(error)

.. code-block:: text

    An anonymous node pattern has no variable. Give the pattern a name before
      using it as an expression.

Property values are expressions. ``param("email")`` renders ``$email``, and a bare
string stays a literal value:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param

    person = node(
        "Person",
        name="p",
        properties={"email": param("email"), "kind": "actor"},
    )
    statement = match(person).returning(person["display_name"])

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person {email: $email, kind: 'actor'}) RETURN p.display_name

The map is snapshotted when the pattern is built, so changing the caller's dictionary
afterwards does not change the pattern. A value that should read a variable needs
``name()`` or a property access, not a bare string.

Add labels to an existing pattern
---------------------------------

``with_labels`` returns a copy with additional labels, so two statements can share a
base pattern and extend it differently:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node

    person = node("Person", name="p")
    statement = match(person.with_labels("Premium")).returning(
        person["display_name"]
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person:Premium) RETURN p.display_name

Duplicate labels and labels already present are ignored, and the original pattern is
unchanged.

Connect two patterns
--------------------

The three factories differ only in the arrow they render. ``relationship_to`` points away
from the node they are called on, ``relationship_from`` points towards it, and
``relationship_with`` renders no arrow:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param

    person = node("Person", name="p")
    movie = node("Movie", name="m")

    acted_in = person.relationship_to(
        movie, "ACTED_IN", name="r", properties={"since": param("since")}
    )
    directed = person.relationship_from(movie, "DIRECTED", name="d")
    related = person.relationship_with(movie, "ACTED_IN")

    renderer = Renderer.get(Configuration(server_version="5.26"))
    outgoing = match(acted_in).returning(person["display_name"])
    incoming = match(directed).returning(person["display_name"])
    undirected = match(related).returning(person["display_name"])

    print(renderer.render(outgoing).cypher)
    print(renderer.render(incoming).cypher)
    print(renderer.render(undirected).cypher)

.. code-block:: cypher

    MATCH (p:Person)-[r:ACTED_IN {since: $since}]->(m:Movie)
    RETURN p.display_name
    MATCH (p:Person)<-[d:DIRECTED]-(m:Movie) RETURN p.display_name
    MATCH (p:Person)-[:ACTED_IN]-(m:Movie) RETURN p.display_name

A hop is one relationship in the pattern. Each hop carries exactly one type. A read
pattern may leave the variable out,
as the third line shows. There is no way to list several types or leave the type out.

Extend a chain across several hops
----------------------------------

The factories on a relationship pattern extend the chain from its current endpoint, which
is how a multi-hop path stays one pattern instead of several:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node

    person = node("Person", name="p")
    movie = node("Movie", name="m")
    series = node("Series", name="s")

    path = (
        person.relationship_to(movie, "ACTED_IN")
        .relationship_to(series, "IN_SERIES")
    )
    statement = match(path).returning(movie["title"], series["title"])

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)-[:ACTED_IN]->(m:Movie)-[:IN_SERIES]->(s:Series)
    RETURN m.title, s.title

Adjacent hops must meet at the same node pattern object, so a chain cannot accidentally
describe two different nodes with one name. Build chains by extending from the endpoint
rather than by constructing hops separately.

Reuse a bound pattern in a write
--------------------------------

A pattern bound by a ``MATCH`` can be an endpoint of a relationship a ``CREATE`` or
``MERGE`` writes:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node

    person = node("Person", name="p")
    movie = node("Movie", name="m")
    statement = match(person).create(person.relationship_to(movie, "ACTED_IN"))

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) CREATE (p)-[:ACTED_IN]->(m:Movie)

A standalone write pattern is different: it declares a new variable, so re-using a bound
pattern as the whole ``MERGE`` pattern is rejected rather than silently redeclared:

.. code-block:: python

    from cypher_dsl import match, node
    from cypher_dsl.errors import DslError

    person = node("Person", name="p")

    try:
        match(person).merge(person)
    except DslError as error:
        print(error)

.. code-block:: text

    MERGE cannot redeclare bound standalone node 'p'.

What to watch out for
---------------------

- A label is required on every node pattern, and a name that cannot be an identifier is
  rejected when the pattern is built.
- Every relationship hop carries exactly one type. ``CREATE`` additionally requires a
  direction, while ``MERGE`` accepts an undirected hop.
- A conflicting label or property declaration on a bound endpoint is rejected rather than
  silently discarded.
- A name that matches a Cypher keyword, such as ``role``, renders backticked. The
  renderer decides that, so the text stays valid without the caller tracking keywords.

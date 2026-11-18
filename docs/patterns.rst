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

``node()`` takes one primary label or a label expression, an optional variable and an
optional property map:

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

.. _label-expression:

Match labels with an expression
-------------------------------

A label expression is a predicate over a node's labels or a relationship's type, built
from :func:`~cypher_dsl.label` terms with ``&`` (both), ``|`` (either) and ``~`` (not,
which renders as ``!``), plus the ``ANY_LABEL`` wildcard for ``%``. Python's operator
precedence matches Cypher's: ``~`` binds tightest, then ``&``, then ``|``. Parentheses in
Python group exactly the way they render:

.. list-table::
   :header-rows: 1

   * - Python
     - Renders in a node pattern
   * - ``label("A")``
     - ``:A``
   * - ``label("A") & label("B")``
     - ``:A&B``
   * - ``label("A") | label("B")``
     - ``:A|B``
   * - ``~label("A")``
     - ``:!A``
   * - ``ANY_LABEL``
     - ``:%``
   * - ``label("A") & (label("B") | label("C"))``
     - ``:A&(B|C)``
   * - ``(label("A") & label("B")) & ~(label("B") & label("C"))``
     - ``:A&B&!(B&C)``
   * - ``~(~label("A"))``
     - ``:!!A``

In a relationship detail the same term text follows the colon inside the brackets, so
``label("R") | label("S")`` renders ``-[:R|S]->``.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, label, match, node

    pattern = node(label("Movie") | label("Person"), name="n")
    statement = match(pattern).returning(pattern["title"])

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (n:Movie|Person) RETURN n.title

The same terms express relationship types. A relationship has exactly one type, so a
union is the useful form, and ``ANY_LABEL`` matches any typed relationship:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, label, match, node

    credits = node("Person", name="p").relationship_to(
        node("Movie"), label("ACTED_IN") | label("DIRECTED"), name="r"
    )
    statement = match(credits).returning(credits["character"])

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person)-[r:ACTED_IN|DIRECTED]->(:Movie) RETURN r.character

- ``node("A")`` and ``with_labels`` keep rendering plain labels, ``:A`` and ``:A:B``.
  ``with_labels`` rejects a pattern whose labels are already an expression; combine the
  terms with ``&`` or ``|`` instead.
- ``CREATE`` and ``MERGE`` attach labels, so they take plain labels and one plain
  relationship type. A ``&``, ``|``, ``!`` or ``%`` term states what to match, not what to
  attach, and is rejected with a remedy.
- The legacy ``:A|:B`` spelling is not a union: it is one type name, so it renders quoted
  and matches only a type with that literal name.

The same terms test an element that is already bound, in an expression position such as
``WHERE`` or ``RETURN``: see
:ref:`label expression predicates <label-expression-predicate>`.

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

A chain is built from relationships. The variable is optional in read and write patterns
alike, as the third line shows. The type is optional in a read pattern; several types are
written as one :ref:`label expression <label-expression>`.

.. _untyped-relationship:

Omit ``relationship_type`` to match a relationship of any type. The arrow then renders
bare, and the variable and property map stay optional inside the brackets:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node

    person = node("Person", name="p")
    movie = node("Movie", name="m")

    any_type = person.relationship_with(movie)
    named = person.relationship_to(movie, name="r")
    dated = person.relationship_from(movie, properties={"since": 1})

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(match(any_type).returning(movie["title"])).cypher)
    print(renderer.render(match(named).returning(movie["title"])).cypher)
    print(renderer.render(match(dated).returning(movie["title"])).cypher)

.. code-block:: text

    MATCH (p:Person)--(m:Movie) RETURN m.title
    MATCH (p:Person)-[r]->(m:Movie) RETURN m.title
    MATCH (p:Person)<-[{since: 1}]-(m:Movie) RETURN m.title

Extend a chain across several relationships
-------------------------------------------

The factories on a relationship pattern extend the chain from its current endpoint, which
is how a path across multiple relationships stays one pattern instead of several:

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

Adjacent relationships must meet at the same node pattern object, so a chain cannot
accidentally describe two different nodes with one name. Build chains by extending from
the endpoint rather than by constructing relationships separately.

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
- A read pattern may leave the relationship type out (:ref:`untyped relationship
  <untyped-relationship>`). ``CREATE`` and ``MERGE`` require exactly one type. ``CREATE``
  additionally requires a direction, while ``MERGE`` accepts an undirected relationship:
  it matches either direction and creates left to right, as the `MERGE manual
  <https://neo4j.com/docs/cypher-manual/5/clauses/merge/#undirected-relationships>`_
  defines.
- A conflicting label or property declaration on a bound endpoint is rejected rather than
  silently discarded.
- A name that matches a Cypher keyword, such as ``role``, renders backticked. The
  renderer decides that, so the text stays valid without the caller tracking keywords.

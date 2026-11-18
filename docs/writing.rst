Create, merge, update and delete
================================

The write :ref:`clauses <clause>` are ``CREATE``, ``MERGE``, ``SET``, ``REMOVE`` and
``DELETE``. Updates are built with ``assign`` and its siblings rather than the operators,
because ``SET n.x = 1`` and the comparison ``n.x == 1`` differ by one character and mean
different things.

Create nodes and relationships
------------------------------

.. _whole-map:

``create`` accepts the same :doc:`patterns <patterns>` as ``match`` plus a whole-map
property: the properties arrive as one map value, such as ``param("props")``, instead of
written-out entries. The server reads that map while it creates the element:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, create, node, param

    person = node(
        "Person",
        name="p",
        properties=param("props", {"email": "ada@example.com"}),
    )
    statement = create(person).returning(person["display_name"])

    renderer = Renderer.get(Configuration(server_version="5.26"))
    rendered = renderer.render(statement)
    print(rendered.cypher)
    print(rendered.parameters)

.. code-block:: text

    CREATE (p:Person $props) RETURN p.display_name
    {'props': {'email': 'ada@example.com'}}

An explicit property map and a map literal render their entries, and a map expression
keeps expression values:

.. code-block:: python

    from cypher_dsl import (
        Configuration,
        Renderer,
        create,
        lit,
        map_,
        name,
        node,
        param,
    )

    explicit = create(
        node("Person", name="p", properties={"email": param("email")})
    )
    literal = create(
        node("Person", name="p", properties=lit({"email": "ada@example.com"}))
    )
    computed = create(
        node(
            "Person",
            name="p",
            properties=map_({"email": name("item")["email"]}),
        )
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(explicit).cypher)
    print(renderer.render(literal).cypher)
    print(renderer.render(computed).cypher)

.. code-block:: cypher

    CREATE (p:Person {email: $email})
    CREATE (p:Person {email: 'ada@example.com'})
    CREATE (p:Person {email: item.email})

A scalar literal or a variable in the property position is rejected, because the grammar
does not accept it. A variable that holds a map needs a ``SET`` operation after the
create.

Every written relationship needs exactly one type, and ``CREATE`` additionally requires a
direction. ``relationship_to`` and ``relationship_from`` supply it, while
``relationship_with`` is a read-only shape.

Merge on an explicit identity
-----------------------------

``MERGE`` searches for the pattern and creates it when it is missing. The identity is the
pattern itself, never the update properties that follow, so the identity entries are
written explicitly. A whole-map parameter cannot serve as identity, because the server
would have to inspect the map first:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, assign, merge, node, param

    person = node("Person", name="p", properties={"email": param("email")})
    statement = (
        merge(person)
        .on_create(assign(person["created_at"], param("now")))
        .returning(person)
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MERGE (p:Person {email: $email}) ON CREATE SET p.created_at = $now RETURN p

Each merge owns at most one ``ON CREATE`` and one ``ON MATCH`` action, and each action
holds any number of assignments in one call. Unlike ``CREATE``, a merged relationship may
be undirected:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, merge, node

    person = node("Person", name="p")
    movie = node("Movie", name="m")
    statement = merge(person.relationship_with(movie, "ACTED_IN"))

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MERGE (p:Person)-[:ACTED_IN]-(m:Movie)

An undirected merge is defined behaviour, not a guess: Cypher matches the relationship in
either direction and, when it creates one, creates it left to right. See the `MERGE manual
<https://neo4j.com/docs/cypher-manual/5/clauses/merge/#undirected-relationships>`_.

A bulk upsert unwinds the rows first and merges per row. See the bulk example in
:doc:`getting-started`.

Set properties and labels
-------------------------

``assign`` replaces one property or the whole element. ``update_properties`` patches a map
into an element, and ``set_labels`` adds labels:

.. code-block:: python

    from cypher_dsl import (
        Configuration,
        Renderer,
        assign,
        match,
        node,
        param,
        set_labels,
        update_properties,
    )

    person = node("Person", name="p")
    rating = match(person).where(person["email"] == param("email")).set_(
        assign(person["rating"], param("rating")),
        set_labels(person, "Premium"),
    ).returning(person["display_name"])
    patch = (
        match(person)
        .set_(update_properties(person, param("changes")))
        .returning(person)
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(rating).cypher)
    print(renderer.render(patch).cypher)

.. code-block:: cypher

    MATCH (p:Person)
      WHERE p.email = $email
    SET p.rating = $rating, p:Premium
    RETURN p.display_name
    MATCH (p:Person) SET p += $changes RETURN p

The two element forms are easy to confuse. ``SET p = $props`` removes every property the
map does not mention, while ``SET p += $changes`` leaves the others in place. A ``+=``
patch targets the element variable itself, not one of its properties.

Remove properties and labels
----------------------------

``remove`` takes property references and label updates. The label form uses the same
``set_labels`` node, which renders ``REMOVE`` instead of ``SET`` in this clause:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, set_labels

    person = node("Person", name="p")
    statement = (
        match(person)
        .remove(person["nickname"], set_labels(person, "Premium"))
        .returning(person)
    )

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(statement).cypher)

.. code-block:: cypher

    MATCH (p:Person) REMOVE p.nickname, p:Premium RETURN p

Delete nodes and relationships
------------------------------

.. _element:

``delete`` and ``detach_delete`` take named elements: the node and relationship
variables of the statement. A node with relationships requires the detached form:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node

    person = node("Person", name="p")
    renderer = Renderer.get(Configuration(server_version="5.26"))

    plain = match(person).delete(person)
    detached = match(person).detach_delete(person)

    print(renderer.render(plain).cypher)
    print(renderer.render(detached).cypher)

.. code-block:: cypher

    MATCH (p:Person) DELETE p
    MATCH (p:Person) DETACH DELETE p

The targets must name elements. An anonymous pattern or a property reference is rejected,
because the clause deletes elements, not values.

Write a property whose name is decided at runtime
-------------------------------------------------

A subscript target keeps the key as syntax, so the property name can come from a
parameter:

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, assign, match, node, param

    person = node("Person", name="p")
    written = (
        match(person)
        .set_(assign(person[param("key")], param("value")))
        .returning(person)
    )
    removed = match(person).remove(person[param("key")]).returning(person)

    renderer = Renderer.get(Configuration(server_version="5.26"))
    print(renderer.render(written).cypher)
    print(renderer.render(removed).cypher)

.. code-block:: cypher

    MATCH (p:Person) SET p[$key] = $value RETURN p
    MATCH (p:Person) REMOVE p[$key] RETURN p

Dynamic property writes arrived in Neo4j 5.24, below this library's 5.26 minimum, so
every release this library supports accepts them. Dynamic subscript reads are not
subject to this write-only restriction.

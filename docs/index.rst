cypher-dsl
==========

Build Cypher queries as Python objects using a DSL and render them to text plus parameters. The
library covers the read and write subset of Cypher 5 that this release implements. It
does not connect to a database, so building a :ref:`statement <statement>` and executing it stay separate
concerns.

.. code-block:: python

    from cypher_dsl import Configuration, Renderer, match, node, param

    movie = node("Movie", name="m")
    statement = (
        match(movie)
        .where(movie["released"] < param("year", 2000))
        .returning(movie["title"])
    )
    renderer = Renderer.get(Configuration(server_version="5.26"))
    rendered = renderer.render(statement)

    assert rendered.cypher == (
        "MATCH (m:Movie) WHERE m.released < $year RETURN m.title"
    )
    assert rendered.parameters == {"year": 2000}

Rendering does not change the statement, and every render returns its own parameter
dictionary: changing one result's dictionary leaves the statement and other results alone.
To reuse one query with different request values, build the parameter with ``param(name)``
and no value. The render reports it under ``unbound_parameters``, and the code that runs
the query supplies the value. Request data goes through ``param()`` and never through
string interpolation.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   getting-started
   patterns
   reading
   writing
   composing
   subqueries
   procedures
   parameters
   targets
   running
   errors
   api

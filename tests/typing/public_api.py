"""
Public typing consumer for the installed distribution.

mypy in strict mode checks the ``assert_type`` calls, which are static assertions and
no-ops at run time. Executing this module exercises the imports and the construction of
every checked value, and ``main`` verifies the selected rendering and bindings. A changed
return type is caught by the type checker, not by execution.
"""

from datetime import date
from typing import assert_type

from cypher_dsl import (
    AliasedExpression,
    AstNode,
    Condition,
    Configuration,
    ElementId,
    ExistsExpression,
    Expression,
    FrozenValue,
    FunctionInvocation,
    Language,
    ListExpression,
    Literal,
    MapExpression,
    NodePattern,
    Parameter,
    RelationshipPattern,
    Rendered,
    Renderer,
    SortItem,
    Statement,
    StatementBuilder,
    SymbolicName,
    UnionStatement,
    Variable,
    asc,
    assign,
    call_procedure,
    count,
    create,
    desc,
    element_id,
    exists,
    fn,
    freeze_value,
    in_,
    list_,
    lit,
    map_,
    match,
    merge,
    name,
    node,
    optional_call_procedure,
    param,
    returning,
    same_binding,
    structurally_equal,
    thaw_value,
    union,
    unwind,
    with_,
)

movie = node("Movie", name="m")
person = node("Person", name="p")

assert_type(movie, NodePattern)
assert_type(movie.with_labels("Film", "Feature"), NodePattern)
assert_type(movie.as_expression(), Variable)
assert_type(movie["released"], Expression)
assert_type(movie[0], Expression)
assert_type(movie["title"].alias("title"), AliasedExpression)

acted_in = person.relationship_to(movie, "ACTED_IN", name="r")
assert_type(acted_in, RelationshipPattern)
assert_type(acted_in.relationship_to(movie, "FOLLOWED_BY"), RelationshipPattern)
assert_type(person.relationship_from(movie, "DIRECTED"), RelationshipPattern)
assert_type(person.relationship_with(movie, "KNOWS"), RelationshipPattern)
assert_type(acted_in.as_expression(), Expression)
assert_type(exists(match(person)), ExistsExpression)

query = match(movie).where(movie["released"] < param("year", 2000)).returning(movie["title"])
assert_type(query, StatementBuilder)
assert_type(match(movie).where(movie["released"] > 1900), StatementBuilder)

projection = match(movie).returning(movie["title"])
assert_type(projection.distinct(), StatementBuilder)
assert_type(projection.order_by(desc(movie["released"]), asc(movie["title"])), StatementBuilder)
assert_type(projection.skip(10), StatementBuilder)
assert_type(projection.limit(param("limit", 10)), StatementBuilder)
assert_type(query.build(), Statement)
assert_type(union(query, query, all=True), UnionStatement)

assert_type(returning(movie["title"]), StatementBuilder)
assert_type(with_(movie), StatementBuilder)
assert_type(create(person), StatementBuilder)
assert_type(merge(person), StatementBuilder)
assert_type(call_procedure("db.labels"), StatementBuilder)
assert_type(optional_call_procedure("apoc.neighbors.tohop", param("start"), "KNOWS>", 1), StatementBuilder)
assert_type(unwind(param("rows"), name("row")), StatementBuilder)
assert_type(match(movie).set_(assign(movie["rating"], param("rating", 4.5))), StatementBuilder)
assert_type(match(movie).delete(movie), StatementBuilder)
assert_type(match(movie).detach_delete(movie), StatementBuilder)

assert_type(asc(movie["released"]), SortItem)
assert_type(desc(movie["released"]), SortItem)
assert_type(count(movie, distinct=True), FunctionInvocation)
assert_type(element_id(movie), ElementId)
assert_type(fn("round", movie["rating"], 2), FunctionInvocation)
assert_type(list_(1, param("title", "Alien")), ListExpression)
assert_type(map_({"title": movie["title"]}), MapExpression)
assert_type(in_(movie["title"], list_("Alien", "Aliens")), Condition)
assert_type(name("row"), Variable)
assert_type(param("year", 2000), Parameter)
assert_type(param("year"), Parameter)
assert_type(lit(2000), Literal)
assert_type(lit([1, 2]), Literal)
assert_type(lit({"year": 2000}), Literal)
assert_type(lit(date(2000, 1, 1)), Literal)
assert_type(SymbolicName("m"), SymbolicName)

frozen = freeze_value([1, 2])
assert_type(frozen, FrozenValue)
assert_type(thaw_value(frozen), object)
assert_type(same_binding(frozen, frozen), bool)
assert_type(structurally_equal(movie, movie), bool)

renderer = Renderer.get(Configuration(server_version="5.26"))
assert_type(renderer, Renderer)
rendered = renderer.render(query)
assert_type(rendered, Rendered)
assert_type(rendered.cypher, str)
assert_type(rendered.parameters, dict[str, object])
assert_type(rendered.unbound_parameters, frozenset[str])
assert_type(str(rendered), str)

configuration = Configuration(server_version="2026.10.2", language=Language.CYPHER_25, always_escape_names=True)
assert_type(configuration.language, Language)
assert_type(Configuration(server_version="5.26").language, Language)


statement = query.build()
assert_type(statement.children(), tuple[AstNode, ...])


def main() -> int:
    """Return zero when the public surface still renders the documented output."""
    if rendered.cypher != "MATCH (m:Movie) WHERE m.released < $year RETURN m.title":
        raise SystemExit(f"unexpected rendering: {rendered.cypher}")
    if rendered.parameters != {"year": 2000}:
        raise SystemExit(f"unexpected parameters: {rendered.parameters}")
    print("public typing consumer rendered the expected query")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

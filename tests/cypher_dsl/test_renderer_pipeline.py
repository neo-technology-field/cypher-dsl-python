import threading

import pytest

from cypher_dsl import Configuration, asterisk, element_id, match, node, param, raw, returning
from cypher_dsl.errors import ConflictingParameterError
from cypher_dsl.render.renderer import Renderer


def test_element_id_renders_on_a_supported_release() -> None:
    person = node("Person", name="p")
    query = match(person).returning(element_id(person))
    rendered = Renderer.get(Configuration(server_version="5.26")).render(query).cypher
    assert rendered == "MATCH (p:Person) RETURN elementId(p)"


def test_mutating_a_result_dictionary_does_not_rebind_later_renders() -> None:
    person = node("Person", name="p")
    query = match(person).where(person["year"] == param("year", 2000)).returning(person)
    renderer = Renderer.get(Configuration(server_version="5.26"))
    first = renderer.render(query)
    first.parameters["year"] = 2020
    assert renderer.render(query).parameters == {"year": 2000}


def test_parameters_inside_an_omitted_declaration_are_still_collected() -> None:
    person = node("Person", name="p", properties={"name": param("name", "Keanu")})
    query = match(person).create(node("Movie", name="m").relationship_from(person, "ACTED_IN")).returning("m")
    rendered = Renderer.get(Configuration(server_version="5.26")).render(query)
    assert rendered.parameters == {"name": "Keanu"}
    assert rendered.cypher.endswith("CREATE (m:Movie)<-[:ACTED_IN]-(p) RETURN m")


def test_with_wildcard_reuses_a_bound_endpoint_through_the_renderer() -> None:
    person = node("Person", name="p")
    query = match(person).with_(asterisk()).create(person.relationship_to(node("Movie"), "ACTED_IN"))

    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (p:Person) WITH * CREATE (p)-[:ACTED_IN]->(:Movie)"
    )


def test_raw_with_conservatively_reuses_a_known_endpoint_through_the_renderer() -> None:
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    query = match(person).with_(raw("p")).create(person.relationship_to(movie, "ACTED_IN"))

    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (p:Person) WITH p CREATE (p)-[:ACTED_IN]->(m:Movie)"
    )


def test_with_wildcard_keeps_the_declaration_of_a_new_endpoint() -> None:
    person = node("Person", name="p")
    movie = node("Movie", name="m")
    query = match(person).with_(asterisk()).create(movie.relationship_to(node("Person"), "LIKES"))

    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (p:Person) WITH * CREATE (m:Movie)-[:LIKES]->(:Person)"
    )


def test_non_wildcard_with_renders_a_dropped_name_as_a_new_declaration() -> None:
    person = node("Person", name="p")
    other = node("Person", name="q")
    movie = node("Movie", name="m")
    query = match(person, other).with_(person).create(other.relationship_to(movie, "LIKES"))

    assert Renderer.get(Configuration(server_version="5.26")).render(query).cypher == (
        "MATCH (p:Person), (q:Person) WITH p CREATE (q:Person)-[:LIKES]->(m:Movie)"
    )


def test_one_shared_renderer_is_safe_for_repeated_and_concurrent_renders() -> None:
    renderer = Renderer.get(Configuration(server_version="5.26"))
    query = returning(param("value", 1))
    results = [renderer.render(query) for _ in range(20)]
    results[0].parameters["value"] = 99
    assert all(result.parameters == {"value": 1} for result in results[1:])

    failures: list[BaseException] = []

    def work() -> None:
        try:
            for _ in range(50):
                renderer.render(query)
        except BaseException as error:
            failures.append(error)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failures == []


def test_binding_conflicts_still_fail_before_text_is_returned() -> None:
    with pytest.raises(ConflictingParameterError):
        Renderer.get(Configuration(server_version="5.26")).render(returning(param("value", True), param("value", 1)))

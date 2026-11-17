from importlib.metadata import metadata
from pathlib import Path

import cypher_dsl


def test_distribution_has_no_runtime_requirements():
    assert metadata("cypher-dsl").get_all("Requires-Dist", []) == []
    assert Path(cypher_dsl.__file__).with_name("py.typed").is_file()


def test_distribution_carries_the_licence_and_the_notice():
    distribution = metadata("cypher-dsl")
    assert distribution["License-Expression"] == "Apache-2.0"
    assert sorted(distribution.get_all("License-File", [])) == ["LICENSE", "NOTICE"]

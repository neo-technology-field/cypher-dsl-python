"""Import boundaries that keep the traversal and analysis free of grammar and target policy."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src" / "cypher_dsl"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def test_traversal_imports_no_concrete_grammar_or_target_policy() -> None:
    imports = imported_modules(ROOT / "render" / "traversal.py")
    forbidden_prefixes = (
        "cypher_dsl.clauses",
        "cypher_dsl.patterns",
        "cypher_dsl.expressions.functions",
        "cypher_dsl.expressions.operators",
        "cypher_dsl.expressions.properties",
        "cypher_dsl.expressions.values",
        "cypher_dsl.render.capabilities",
        "cypher_dsl.render.configuration",
        "cypher_dsl.render.targets",
    )
    assert not [module for module in imports if module.startswith(forbidden_prefixes)]


def test_analysis_imports_nothing_under_render() -> None:
    imports = imported_modules(ROOT / "statements" / "analysis.py")
    assert not [module for module in imports if module.startswith("cypher_dsl.render")]


def test_construct_renderers_import_no_target_policy_or_binding_collection() -> None:
    for module in ("expressions", "patterns", "projections", "updates", "statements"):
        path = ROOT / "render" / f"{module}.py"
        if not path.exists():
            continue
        imports = imported_modules(path)
        forbidden = (
            "cypher_dsl.render.bindings",
            "cypher_dsl.render.capabilities",
            "cypher_dsl.render.configuration",
            "cypher_dsl.render.targets",
        )
        assert not [name for name in imports if name.startswith(forbidden)], module


def test_features_imports_nothing_under_render() -> None:
    imports = imported_modules(ROOT / "features.py")
    assert not [module for module in imports if module.startswith("cypher_dsl.render")]

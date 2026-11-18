"""Execute the examples on the supported-Cypher page.

A supported claim is a pair of blocks: Python that builds and prints, followed by the
Cypher it renders or the error text it prints. Running every pair here means a documented
claim cannot drift from the library without failing the suite.

Line breaks and indentation are not compared. The page fits a statement into 80 columns by
breaking it at clause boundaries, while the renderer emits one line, and pretty printing
wraps at 120. The words and their order are what the page claims, so those are pinned.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path
from typing import Final

import pytest

PAGE: Final = Path(__file__).resolve().parents[2] / "docs" / "support.rst"

Block = tuple[str, str]


def _code_blocks(text: str) -> list[Block]:
    """Return the page's code blocks as (kind, body) in document order."""
    lines = text.splitlines()
    blocks: list[Block] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith(".. code-block:: "):
            index += 1
            continue
        kind = line.removeprefix(".. code-block:: ").strip()
        body: list[str] = []
        index += 1
        while index < len(lines) and (not lines[index].strip() or lines[index].startswith("    ")):
            body.append(lines[index][4:] if lines[index].startswith("    ") else "")
            index += 1
        blocks.append((kind, "\n".join(body).strip("\n")))
    return blocks


def _example_pairs() -> list[tuple[str, str]]:
    """Return (python source, expected output) for every pair on the page."""
    blocks = _code_blocks(PAGE.read_text())
    pairs: list[tuple[str, str]] = []
    for position, (kind, body) in enumerate(blocks):
        if kind != "python":
            continue
        if position + 1 == len(blocks) or blocks[position + 1][0] not in {"cypher", "text"}:
            raise AssertionError(f"The python block at position {position} has no following cypher or text block.")
        pairs.append((body, blocks[position + 1][1]))
    return pairs


PAIRS: Final = _example_pairs()


def _unwrapped(text: str) -> str:
    """Collapse the line breaks and indentation the page uses to fit a block into 80 columns."""
    return " ".join(line.strip() for line in text.splitlines())


def test_the_page_has_examples():
    """A page with no pairs would pass this suite while documenting nothing."""
    assert len(PAIRS) >= 10


@pytest.mark.parametrize(
    ("source", "expected"),
    PAIRS,
    ids=[f"example-{number}" for number in range(len(PAIRS))],
)
def test_page_example_renders_what_it_documents(source: str, expected: str) -> None:
    """Run one example and compare its output with the block beneath it."""
    output = io.StringIO()
    namespace: dict[str, object] = {"__name__": "__main__"}
    with redirect_stdout(output):
        exec(compile(source, str(PAGE), "exec"), namespace)
    assert _unwrapped(output.getvalue()) == _unwrapped(expected)

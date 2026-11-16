"""
Turn Nox's own session listing into the GitHub Actions job matrix.

CI could keep a list of session names and interpreters, but such a list becomes stale: a
new Nox session or a changed Python classifier would produce a workflow that runs fewer
jobs than the project promises, without any error. The workflow therefore asks Nox for its
sessions and converts that listing here. The output is data; the only command CI runs per
job is Nox itself.

Every job runs on exactly one interpreter, so a GitHub matrix entry can select it. A
session that spans several interpreters must be split in the Nox file instead of being
silently collapsed here.
"""

from __future__ import annotations

import json
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import click

AGGREGATE_SESSION = "matrix"
OTHER_JOBS = ("quality", "docs", "package")
DEFAULT_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
_CLASSIFIER_PREFIX = "Programming Language :: Python :: 3."


class CiSessionError(ValueError):
    """Raised when a Nox listing cannot be turned into an unambiguous job matrix."""


@dataclass(frozen=True)
class CiJob:
    """
    One GitHub matrix entry.

    Attributes:
        session: Nox session name, passed to ``nox -s``.
        interpreter: CPython version the job installs and the session declares.
    """

    session: str
    interpreter: str

    def as_entry(self) -> dict[str, str]:
        """Return the matrix entry with the field names the workflow interpolates."""
        return {"session": self.session, "python": self.interpreter}


def load_python_versions(pyproject: Path) -> tuple[str, ...]:
    """
    Read the supported CPython minors from the project's trove classifiers.

    The classifiers are the published support promise and the same source the Nox file
    uses, so CI cannot advertise a matrix that differs from the metadata.

    Args:
        pyproject: Path to the project's ``pyproject.toml``.

    Returns:
        Version strings in ascending order, for example ``("3.11", "3.12")``.

    Raises:
        CiSessionError: If no Python 3 minor classifier is present.
    """
    try:
        document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise CiSessionError(f"Could not read {pyproject}: {error}") from error

    classifiers = document.get("project", {}).get("classifiers", [])
    versions = [
        classifier.rsplit(" ", 1)[-1]
        for classifier in classifiers
        if isinstance(classifier, str) and classifier.startswith(_CLASSIFIER_PREFIX)
    ]
    if not versions:
        raise CiSessionError(
            f"{pyproject} has no 'Programming Language :: Python :: 3.x' classifier, "
            "so the supported interpreter set cannot be derived."
        )
    return tuple(sorted(versions, key=_minor_version))


def _minor_version(version: str) -> tuple[int, ...]:
    """Sort version strings numerically rather than lexicographically."""
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError as error:
        raise CiSessionError(f"Unsupported interpreter classifier value {version!r}.") from error


def build_jobs(listing: object, python_versions: Sequence[str]) -> tuple[CiJob, ...]:
    """
    Convert ``nox --list --json`` output into matrix entries.

    Args:
        listing: Parsed JSON listing from ``nox --list --json``.
        python_versions: Supported CPython minors, used to require one unit job each.

    Returns:
        One job per non-aggregate session, in Nox definition order.

    Raises:
        CiSessionError: If the listing is malformed, repeats a session, leaves a session
            without a single pinned interpreter, or does not match the sessions the
            project declares.
    """
    sessions = _sessions(listing)
    jobs: list[CiJob] = []
    issues: list[str] = []
    for name, declared in sessions:
        if name == AGGREGATE_SESSION:
            continue
        try:
            jobs.append(CiJob(name, _single_interpreter(name, declared)))
        except CiSessionError as error:
            issues.append(str(error))

    expected = {f"tests-{version}" for version in python_versions} | set(OTHER_JOBS)
    actual = {job.session for job in jobs}
    issues.extend(f"missing Nox session {name!r}." for name in sorted(expected - actual))
    issues.extend(f"unexpected Nox session {name!r}." for name in sorted(actual - expected))
    if issues:
        raise CiSessionError("\n".join(issues))
    return tuple(jobs)


def _sessions(listing: object) -> list[tuple[str, object]]:
    """Validate the listing envelope and session names, rejecting duplicates."""
    if not isinstance(listing, list):
        raise CiSessionError("The Nox session listing must be a JSON array.")

    sessions: list[tuple[str, object]] = []
    seen: set[str] = set()
    issues: list[str] = []
    for entry in listing:
        if not isinstance(entry, dict) or not isinstance(entry.get("session"), str) or not entry["session"]:
            issues.append(f"Every Nox session entry needs a non-empty 'session' name, got {entry!r}.")
            continue
        name = entry["session"]
        if name in seen:
            issues.append(f"duplicate Nox session {name!r}.")
            continue
        seen.add(name)
        sessions.append((name, entry.get("python")))
    if issues:
        raise CiSessionError("\n".join(issues))
    return sessions


def _single_interpreter(name: str, declared: object) -> str:
    """
    Return the interpreter a session declares, rejecting inherited defaults.

    ``nox --list --json`` reports a parameterised session's interpreter as one string.
    ``null`` means the session accepts whatever interpreter invoked Nox, which would make
    the GitHub job depend on the discover runner instead of on the project metadata.
    """
    if not isinstance(declared, str) or not declared:
        raise CiSessionError(
            f"Nox session {name!r} must declare exactly one interpreter, got {declared!r}. "
            "Pin it in the session decorator instead of relying on the ambient interpreter."
        )
    return declared


def matrix_document(jobs: Sequence[CiJob]) -> dict[str, list[dict[str, str]]]:
    """Wrap jobs in the ``include`` key a GitHub matrix consumes."""
    return {"include": [job.as_entry() for job in jobs]}


@click.command()
@click.argument("listing", default="-")
@click.option(
    "--pyproject",
    type=click.Path(path_type=Path),
    default=DEFAULT_PYPROJECT,
    show_default=True,
    help="Project metadata whose classifiers define the supported interpreters.",
)
def main(listing: str, pyproject: Path) -> None:
    """Print the matrix document, reporting invalid Nox metadata without a traceback."""
    try:
        jobs = build_jobs(_read_listing(listing), load_python_versions(pyproject))
    except CiSessionError as error:
        raise click.ClickException(str(error)) from error
    click.echo(json.dumps(matrix_document(jobs), separators=(",", ":")))


def _read_listing(path: str) -> object:
    """Read the listing from a file or standard input."""
    try:
        if path == "-":
            return json.load(sys.stdin)
        with Path(path).open(encoding="utf-8") as source:
            return json.load(source)
    except (OSError, json.JSONDecodeError) as error:
        raise CiSessionError(f"Could not read the Nox session listing from {path}: {error}") from error


if __name__ == "__main__":
    main()

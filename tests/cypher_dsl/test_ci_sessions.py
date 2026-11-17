"""
Contract tests for the job matrix that CI derives from Nox's session listing.

The inputs are synthetic copies of ``nox --list --json`` metadata, so the tests never
start Nox, Docker or an interpreter. They pin the properties CI relies on: the aggregate
session is not a job, every job names exactly one interpreter, no session is listed
twice, and the unit jobs match the supported Python classifiers in ``pyproject.toml``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path

import pytest
from click.testing import CliRunner

from tools.ci_sessions import (
    AGGREGATE_SESSION,
    OTHER_JOBS,
    CiJob,
    CiSessionError,
    build_jobs,
    load_python_versions,
    main,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"

# The published support promise from the design. CI itself reads the classifiers; this
# constant exists so a classifier edit that silently drops a promised minor fails here.
SUPPORTED_MINORS = ("3.11", "3.12", "3.13", "3.14", "3.15")


def _listing(
    versions: Sequence[str],
    other_jobs: Sequence[str] = OTHER_JOBS,
    include_aggregate: bool = True,
) -> list[dict[str, object]]:
    """Build a Nox listing shaped like ``nox --list --json`` output."""
    entries: list[dict[str, object]] = []
    if include_aggregate:
        entries.append({"session": AGGREGATE_SESSION, "python": None})
    entries.extend({"session": f"tests-{version}", "python": version} for version in versions)
    entries.extend({"session": session, "python": "3.15"} for session in other_jobs)
    return entries


def test_jobs_exclude_the_aggregate_and_keep_definition_order():
    jobs = build_jobs(_listing(SUPPORTED_MINORS), SUPPORTED_MINORS)

    assert [job.session for job in jobs] == [
        *(f"tests-{version}" for version in SUPPORTED_MINORS),
        *OTHER_JOBS,
    ]
    assert jobs[0] == CiJob("tests-3.11", "3.11")
    assert CiJob("quality", "3.15") in jobs
    assert all(job.session != AGGREGATE_SESSION for job in jobs)


def test_duplicate_sessions_are_rejected():
    listing = _listing(SUPPORTED_MINORS)
    listing.append({"session": "quality", "python": "3.15"})

    with pytest.raises(CiSessionError, match="duplicate Nox session 'quality'"):
        build_jobs(listing, SUPPORTED_MINORS)


def test_missing_unit_session_is_rejected():
    listing = [entry for entry in _listing(SUPPORTED_MINORS) if entry["session"] != "tests-3.14"]

    with pytest.raises(CiSessionError, match=re.escape("missing Nox session 'tests-3.14'")):
        build_jobs(listing, SUPPORTED_MINORS)


def test_missing_shared_job_is_rejected():
    listing = [entry for entry in _listing(SUPPORTED_MINORS) if entry["session"] != "docs"]

    with pytest.raises(CiSessionError, match="missing Nox session 'docs'"):
        build_jobs(listing, SUPPORTED_MINORS)


def test_unexpected_session_is_rejected():
    listing = _listing(SUPPORTED_MINORS)
    listing.append({"session": "release", "python": "3.15"})

    with pytest.raises(CiSessionError, match="unexpected Nox session 'release'"):
        build_jobs(listing, SUPPORTED_MINORS)


def test_session_without_a_pinned_interpreter_is_rejected():
    listing = [entry for entry in _listing(SUPPORTED_MINORS) if entry["session"] != "docs"]
    listing.append({"session": "docs", "python": None})

    with pytest.raises(CiSessionError, match="'docs' must declare exactly one interpreter"):
        build_jobs(listing, SUPPORTED_MINORS)


def test_session_with_several_interpreters_is_rejected():
    listing = [entry for entry in _listing(SUPPORTED_MINORS) if entry["session"] != "quality"]
    listing.append({"session": "quality", "python": ["3.14", "3.15"]})

    with pytest.raises(CiSessionError, match="'quality' must declare exactly one interpreter"):
        build_jobs(listing, SUPPORTED_MINORS)


def test_coverage_follows_the_project_classifiers(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "\n".join(
            [
                "[project]",
                "classifiers = [",
                *(f'  "Programming Language :: Python :: {version}",' for version in (*SUPPORTED_MINORS, "3.16")),
                "]",
            ]
        ),
        encoding="utf-8",
    )

    versions = load_python_versions(pyproject)

    assert versions == (*SUPPORTED_MINORS, "3.16")
    with pytest.raises(CiSessionError, match=re.escape("missing Nox session 'tests-3.16'")):
        build_jobs(_listing(SUPPORTED_MINORS), versions)


def test_project_metadata_publishes_the_supported_minors():
    assert load_python_versions(PYPROJECT_PATH) == SUPPORTED_MINORS


def test_missing_python_classifiers_are_rejected(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nclassifiers = ["Typing :: Typed"]\n', encoding="utf-8")

    with pytest.raises(CiSessionError, match="classifier"):
        load_python_versions(pyproject)


def test_cli_writes_the_github_matrix(tmp_path):
    listing_path = tmp_path / "nox-sessions.json"
    listing_path.write_text(json.dumps(_listing(SUPPORTED_MINORS)), encoding="utf-8")

    result = CliRunner().invoke(main, [str(listing_path)])

    assert result.exit_code == 0, result.output
    output = json.loads(result.stdout)
    assert output["include"] == [
        *({"session": f"tests-{version}", "python": version} for version in SUPPORTED_MINORS),
        *({"session": session, "python": "3.15"} for session in OTHER_JOBS),
    ]


def test_cli_reports_invalid_metadata(tmp_path):
    listing_path = tmp_path / "nox-sessions.json"
    listing_path.write_text(json.dumps([{"session": "tests-3.11", "python": "3.11"}]), encoding="utf-8")

    result = CliRunner().invoke(main, [str(listing_path)])

    assert result.exit_code == 1
    assert "missing Nox session" in result.stderr


def test_cli_reads_standard_input_by_default():
    result = CliRunner().invoke(main, input=json.dumps(_listing(SUPPORTED_MINORS)))
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.stdout)["include"]) == 9


def test_cli_reports_malformed_json_without_a_traceback():
    result = CliRunner().invoke(main, input="not JSON")
    assert result.exit_code == 1
    assert "Could not read the Nox session listing" in result.stderr
    assert "Traceback" not in result.output


def test_cli_accepts_an_explicit_metadata_path(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nclassifiers = ["Programming Language :: Python :: 3.16"]\n', encoding="utf-8")
    result = CliRunner().invoke(
        main,
        ["-", "--pyproject", str(pyproject)],
        input=json.dumps(_listing(("3.16",))),
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["include"][0] == {"session": "tests-3.16", "python": "3.16"}


def test_cli_help_does_not_require_a_listing():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "--pyproject" in result.output

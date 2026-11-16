"""
Nox sessions for the project.

``tests-<minor>`` runs the unit suite once per supported CPython minor. The versions come
from the project classifiers, so the matrix and the published support promise cannot
drift apart.
``quality`` runs the static checks,
``docs`` builds the offline documentation,
``package`` builds and smokes the installed wheel.
``matrix`` only notifies those unique sessions; it never runs a test itself.

Every session pins its interpreter and a missing interpreter is an error. An incomplete
interpreter set is an incomplete matrix, not a smaller one.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import nox

PROJECT_ROOT = Path(__file__).resolve().parent
DISTRIBUTIONS = "dist"
SMOKE_SCRIPT = PROJECT_ROOT / "tests" / "smoke" / "check_install.py"
PYTHON_VERSIONS = tuple(nox.project.python_versions(nox.project.load_toml(PROJECT_ROOT / "pyproject.toml")))
CURRENT_PYTHON = PYTHON_VERSIONS[-1]

# Nox's JSON listing reports only the sessions selected for this run, and a run without
# arguments selects the aggregate alone. Tagging every session lets CI ask for the full
# list with ``nox -t ci --list --json`` without enumerating session names a second time.
CI_TAG = "ci"

nox.options.error_on_missing_interpreters = True


def sync_groups(session: nox.Session, groups: tuple[str, ...]) -> None:
    """Install dependency groups non-editably for the session.

    The package is reinstalled on every sync. Without that, uv keeps an earlier
    non-editable copy on disk and the session would test a stale revision of the source
    tree instead of the one checked out here.

    Args:
        session: Session whose virtualenv receives the dependencies.
        groups: Dependency group names declared in ``pyproject.toml``.
    """
    arguments = [
        "uv",
        "sync",
        "--no-default-groups",
        "--no-editable",
        f"--python={session.virtualenv.location}",
        "--reinstall-package",
        "cypher-dsl",
    ]
    for group in groups:
        arguments.extend(("--group", group))
    session.run_install(
        *arguments,
        env={"UV_PROJECT_ENVIRONMENT": session.virtualenv.location},
    )


@nox.session(python=list(PYTHON_VERSIONS), venv_backend="uv", default=False, tags=[CI_TAG])
def tests(session: nox.Session) -> None:
    """Run ordinary pytest discovery on the session's interpreter."""
    sync_groups(session, ("test",))
    session.run("pytest", *session.posargs)


@nox.session(python=CURRENT_PYTHON, venv_backend="uv", default=False, tags=[CI_TAG])
def quality(session: nox.Session) -> None:
    """Check lint, formatting and strict typing against the installed package."""
    sync_groups(session, ("dev",))
    session.run("ruff", "check", ".")
    session.run("ruff", "format", "--check", ".")
    session.run("mypy")


@nox.session(python=CURRENT_PYTHON, venv_backend="uv", default=False, tags=[CI_TAG])
def docs(session: nox.Session) -> None:
    """Build the documentation without network access."""
    sync_groups(session, ("docs",))
    session.run("sphinx-build", "-W", "--keep-going", "-b", "html", "docs", "docs/_build/html")


@nox.session(python=CURRENT_PYTHON, venv_backend="uv", default=False, tags=[CI_TAG])
def package(session: nox.Session) -> None:
    """Build a wheel from an sdist, install only the wheel, then smoke it."""
    shutil.rmtree(DISTRIBUTIONS, ignore_errors=True)
    session.run("uv", "build", "--sdist", "--out-dir", DISTRIBUTIONS, external=True)
    sdist = _single_artifact("*.tar.gz")
    import tarfile

    with tarfile.open(sdist) as archive:
        names = set(archive.getnames())
    expected = "docs/contributor/architecture.md"
    assert any(name.endswith(expected) for name in names), f"sdist is missing {expected}"
    session.run("uv", "build", "--wheel", sdist, "--out-dir", DISTRIBUTIONS, external=True)
    wheel = _single_artifact("*.whl")
    session.run_install(
        "uv",
        "pip",
        "install",
        "--no-deps",
        "--reinstall-package",
        "cypher-dsl",
        f"--python={session.virtualenv.location}",
        wheel,
    )
    with tempfile.TemporaryDirectory() as workdir:
        session.chdir(workdir)
        session.run("python", "-I", str(SMOKE_SCRIPT))


@nox.session(venv_backend="none", default=True, tags=[CI_TAG])
def matrix(session: nox.Session) -> None:
    """Notify every unique session above exactly once."""
    for version in PYTHON_VERSIONS:
        session.notify(f"tests-{version}")
    for check in ("quality", "docs", "package"):
        session.notify(check)


def _single_artifact(pattern: str) -> str:
    """Return the one expected build artifact, failing on a stale or missing output."""
    matches = sorted(Path(DISTRIBUTIONS).glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {pattern} in {DISTRIBUTIONS}, found {len(matches)}")
    return str(matches[0])

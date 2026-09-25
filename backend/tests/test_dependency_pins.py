"""The image build must install the dependency set the test suite ran against.

pyproject.toml declares only lower bounds, so an image built without a warm
Docker cache resolved whatever was newest that day. On 2026-09-25 a rebuild
after `docker builder prune` pulled a SQLAlchemy whose default driver for
`postgresql://` is psycopg 3, and `alembic upgrade head` died with
`ModuleNotFoundError: No module named 'psycopg'` mid-deploy. The pins in
constraints.txt are the tested set; these tests keep the build using them.
"""

import re
import shlex
import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(spec: str) -> str:
    return _normalise(re.split(r"[\[<>=!~; ]", spec, maxsplit=1)[0])


def _pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in (BACKEND / "constraints.txt").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        name, sep, version = line.partition("==")
        assert sep, f"constraints.txt entry is not an exact pin: {line!r}"
        pins[_normalise(name)] = version
    return pins


def test_every_declared_dependency_is_pinned():
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text())["project"]
    declared = list(project["dependencies"])
    for extra in project.get("optional-dependencies", {}).values():
        declared.extend(extra)

    pins = _pins()
    missing = sorted({_requirement_name(d) for d in declared} - pins.keys())
    assert not missing, f"declared but not pinned in constraints.txt: {missing}"


def test_sync_driver_is_psycopg2():
    # DATABASE_URL_SYNC is a bare postgresql:// URL, used by Alembic.
    pins = _pins()
    assert "psycopg2-binary" in pins
    assert pins["sqlalchemy"].startswith("2.0."), (
        "SQLAlchemy 2.1 changes the default postgresql:// driver to psycopg 3; "
        "move DATABASE_URL_SYNC to an explicit driver before raising this pin"
    )


def _project_installs(dockerfile: str) -> list[list[str]]:
    """Every `pip install` of the project itself (`.` or `.[extra]`), as argv."""
    installs = []
    for line in dockerfile.splitlines():
        for command in line.split("&&"):
            if "pip install" not in command:
                continue  # also skips `\` continuation lines shlex cannot parse
            argv = shlex.split(command.removeprefix("RUN").strip())
            if argv[:2] == ["pip", "install"] and any(
                a == "." or a.startswith(".[") for a in argv[2:]
            ):
                installs.append(argv)
    return installs


def test_dockerfile_installs_the_project_under_the_constraints():
    installs = _project_installs((BACKEND / "Dockerfile").read_text())
    # base stage (`.`) and development stage (`.[dev]`)
    assert len(installs) == 2, installs
    for argv in installs:
        pairs = list(zip(argv, argv[1:], strict=False))
        assert ("-c", "constraints.txt") in pairs, f"unconstrained install: {' '.join(argv)}"

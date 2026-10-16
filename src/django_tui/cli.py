"""The `django-tui` command: run the TUI in a Django project that doesn't have django-tui installed.

`uvx django-tui` finds the project's manage.py, loads its .env files and switches to the project's virtual environment.
Then it runs manage.py as if it were `python manage.py tui`, so that everything manage.py sets up (the settings module,
sys.path, environment variables) works like it does for the project's own commands.
"""

from __future__ import annotations

import os
import runpy
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

from dotenv import load_dotenv

import django_tui

# Set in the project's Python after switching to it, so that it doesn't look for a virtual environment again
REEXEC_ENV = "DJANGO_TUI_REEXEC"
# The directories that django-tui and its dependencies are installed in, for the project's Python
PATH_ENV = "DJANGO_TUI_PATH"

VENV_NAMES = (".venv", "venv", "env", ".env")
# Directories that never contain the project's manage.py
SKIP_DIRS = {"node_modules", "site-packages", "__pycache__"}
SEARCH_DEPTH = 2

# Runs in the project's Python. Imports django-tui from where it's installed, but its dependencies from the project
# first, so that the project uses its own Django.
BOOTSTRAP = f"""\
import os, sys
if sys.version_info < (3, 11):
    sys.exit("django-tui requires Python 3.11 or newer, the project's virtual environment has " + sys.version.split()[0])
paths = os.environ.pop({PATH_ENV!r}).split(os.pathsep)
sys.path[:0] = paths
import django_tui.cli
del sys.path[: len(paths)]
sys.path.extend(paths)
django_tui.cli.main()
"""


class ProjectNotFound(Exception):
    pass


def find_manage_py(start: Path) -> Path:
    """Find manage.py in `start` or its parents, or else in its subdirectories."""
    for directory in (start, *start.parents):
        if (directory / "manage.py").is_file():
            return directory / "manage.py"
    found = sorted(_search(start, SEARCH_DEPTH))
    if len(found) == 1:
        return found[0]
    if found:
        paths = "\n".join(f"  {path.relative_to(start)}" for path in found)
        raise ProjectNotFound(f"Found more than one manage.py, cd into the project you want to open:\n{paths}")
    raise ProjectNotFound(f"Couldn't find manage.py in {start} or near it. Run django-tui in your Django project.")


def _search(directory: Path, depth: int) -> Iterator[Path]:
    try:
        children = sorted(directory.iterdir())
    except OSError:
        return
    for child in children:
        if not child.is_dir() or child.name.startswith(".") or child.name in SKIP_DIRS or is_venv(child):
            continue
        if (child / "manage.py").is_file():
            yield child / "manage.py"
        elif depth > 1:
            yield from _search(child, depth - 1)


def is_venv(directory: Path) -> bool:
    return (directory / "pyvenv.cfg").is_file()


def venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def project_dirs(project: Path) -> Iterator[Path]:
    """The project's directory and its parents, up to the repository's root."""
    for directory in (project, *project.parents):
        yield directory
        if (directory / ".git").exists():
            return


def find_venv(project: Path) -> Path | None:
    """Find the project's virtual environment: the active one, or one in the project or its parents."""
    active = os.environ.get("VIRTUAL_ENV")
    if active and is_venv(Path(active)):
        return Path(active)
    for directory in project_dirs(project):
        for name in VENV_NAMES:
            if is_venv(directory / name):
                return directory / name
    return None


def load_env_files(project: Path) -> None:
    """Load the .env files in the project and its parents. Variables that are already set and the ones in the files
    closer to the project win."""
    for directory in project_dirs(project):
        if (directory / ".env").is_file():
            load_dotenv(directory / ".env", override=False)


def install_paths() -> list[str]:
    """The directories that django-tui and its dependencies are installed in."""
    paths = [str(Path(django_tui.__file__).parent.parent)]
    for path in sys.path:
        if Path(path).name in ("site-packages", "dist-packages") and path not in paths:
            paths.append(path)
    return paths


def switch_to(python: Path, args: list[str]) -> None:
    """Run django-tui again in the project's Python."""
    env = {**os.environ, REEXEC_ENV: "1", PATH_ENV: os.pathsep.join(install_paths())}
    argv = [str(python), "-c", BOOTSTRAP, *args]
    if os.name == "nt":
        # Windows doesn't replace the running process with exec, so the terminal would get two of them
        sys.exit(subprocess.call(argv, env=env))
    os.execve(python, argv, env)


def with_tui(get_commands):
    """Add the tui command to the project's commands, as if django_tui were in INSTALLED_APPS."""

    def wrapper():
        return {**get_commands(), "tui": "django_tui"}

    wrapper.cache_clear = get_commands.cache_clear
    return wrapper


def run_manage_py(manage_py: Path, args: list[str]) -> None:
    """Run manage.py like `python manage.py tui` would."""
    # Not imported at the top: the bootstrap imports this module before the project's Django is on sys.path
    from django.core import management

    project = manage_py.parent
    os.chdir(project)
    sys.path.insert(0, str(project))
    sys.argv = [str(manage_py), "tui", *args]
    management.get_commands = with_tui(management.get_commands)
    runpy.run_path(str(manage_py), run_name="__main__")


def main() -> None:
    args = sys.argv[1:]
    try:
        manage_py = find_manage_py(Path.cwd())
    except ProjectNotFound as e:
        sys.exit(str(e))
    project = manage_py.parent

    if not os.environ.get(REEXEC_ENV):
        load_env_files(project)
        venv = find_venv(project)
        if venv is not None and Path(sys.prefix).resolve() != venv.resolve():
            python = venv_python(venv)
            if python.is_file():
                switch_to(python, args)

    try:
        run_manage_py(manage_py, args)
    except ModuleNotFoundError as e:
        hint = (
            f"Is {project} the right project?"
            if os.environ.get(REEXEC_ENV)
            else "Activate the project's virtual environment and run django-tui again."
        )
        sys.exit(f"Couldn't import {e.name!r} for the project in {project}. {hint}")


if __name__ == "__main__":
    main()

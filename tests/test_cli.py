import os
import subprocess
import sys
import venv
from pathlib import Path

import pytest

from django_tui.cli import ProjectNotFound, find_manage_py, find_venv, load_env_files

MANAGE_PY = """\
import os
import sys

from django.core.management import execute_from_command_line

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mysite.settings")
execute_from_command_line(sys.argv)
"""

SETTINGS = """\
import os
import sys

print("prefix:", sys.prefix)
SECRET_KEY = os.environ["SECRET_FROM_DOTENV"]
INSTALLED_APPS = ["django.contrib.auth", "django.contrib.contenttypes"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
"""


def make_project(directory: Path) -> Path:
    (directory / "mysite").mkdir(parents=True)
    (directory / "mysite" / "__init__.py").touch()
    (directory / "mysite" / "settings.py").write_text(SETTINGS)
    (directory / "manage.py").write_text(MANAGE_PY)
    return directory / "manage.py"


def make_venv(directory: Path) -> Path:
    directory.mkdir(parents=True)
    (directory / "pyvenv.cfg").touch()
    return directory


def run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    return subprocess.run(
        [sys.executable, "-c", "from django_tui.cli import main; main()", *args],
        check=False,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_find_manage_py_in_the_directory_or_its_parents(tmp_path):
    manage_py = make_project(tmp_path)

    assert find_manage_py(tmp_path) == manage_py
    assert find_manage_py(tmp_path / "mysite") == manage_py


def test_find_manage_py_in_subdirectories(tmp_path):
    manage_py = make_project(tmp_path / "backend" / "src")
    make_project(tmp_path / ".venv" / "lib")
    make_project(tmp_path / "node_modules" / "package")

    assert find_manage_py(tmp_path) == manage_py


def test_find_manage_py_errors(tmp_path):
    with pytest.raises(ProjectNotFound, match="Couldn't find manage.py"):
        find_manage_py(tmp_path)

    make_project(tmp_path / "one")
    make_project(tmp_path / "two")
    with pytest.raises(ProjectNotFound, match="more than one manage.py"):
        find_manage_py(tmp_path)


def test_find_venv(tmp_path, monkeypatch):
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    project = tmp_path / "repo" / "backend"
    project.mkdir(parents=True)
    (tmp_path / "repo" / ".git").mkdir()
    make_venv(tmp_path / ".venv")

    assert find_venv(project) is None

    repo_venv = make_venv(tmp_path / "repo" / "venv")
    assert find_venv(project) == repo_venv

    project_venv = make_venv(project / ".venv")
    assert find_venv(project) == project_venv

    monkeypatch.setenv("VIRTUAL_ENV", str(repo_venv))
    assert find_venv(project) == repo_venv


def test_load_env_files(tmp_path, monkeypatch):
    project = tmp_path / "repo" / "backend"
    project.mkdir(parents=True)
    (tmp_path / "repo" / ".git").mkdir()
    (tmp_path / ".env").write_text("DJANGO_TUI_OUTSIDE=1\n")
    (tmp_path / "repo" / ".env").write_text("DJANGO_TUI_A=repo\nDJANGO_TUI_B=repo\n")
    (project / ".env").write_text("DJANGO_TUI_A=project\nDJANGO_TUI_SET=project\n")
    for name in ("DJANGO_TUI_OUTSIDE", "DJANGO_TUI_A", "DJANGO_TUI_B"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DJANGO_TUI_SET", "already set")

    load_env_files(project)

    assert os.environ["DJANGO_TUI_A"] == "project"
    assert os.environ["DJANGO_TUI_B"] == "repo"
    assert os.environ["DJANGO_TUI_SET"] == "already set"
    assert "DJANGO_TUI_OUTSIDE" not in os.environ


def test_cli_runs_the_tui_command_in_a_project(tmp_path):
    (tmp_path / ".git").mkdir()
    make_project(tmp_path)
    (tmp_path / ".env").write_text("SECRET_FROM_DOTENV=secret\n")

    result = run_cli(tmp_path / "mysite", "--help")

    assert result.returncode == 0, result.stderr
    assert "usage: manage.py tui" in result.stdout
    assert f"prefix: {sys.prefix}" in result.stdout


def test_cli_switches_to_the_projects_venv(tmp_path):
    (tmp_path / ".git").mkdir()
    make_project(tmp_path)
    (tmp_path / ".env").write_text("SECRET_FROM_DOTENV=secret\n")
    venv.create(tmp_path / ".venv", symlinks=os.name != "nt")

    result = run_cli(tmp_path, "--help")

    assert result.returncode == 0, result.stderr
    assert "usage: manage.py tui" in result.stdout
    assert f"prefix: {tmp_path / '.venv'}" in result.stdout


def test_cli_without_a_project(tmp_path):
    result = run_cli(tmp_path)

    assert result.returncode == 1
    assert "Couldn't find manage.py" in result.stderr

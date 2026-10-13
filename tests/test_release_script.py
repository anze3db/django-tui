"""scripts/release.py: CalVer, changelog generation and extraction (no network)."""

from __future__ import annotations

import datetime as dt
import importlib.util
import re
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("release", Path(__file__).parent.parent / "scripts" / "release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

D = dt.date(2026, 10, 8)


@pytest.mark.parametrize(
    ("tags", "today", "expected"),
    [
        ([], D, "26.1"),
        (["26.1", "26.2"], D, "26.3"),
        (["26.9", "26.10"], D, "26.11"),  # numeric, not lexical
        (["25.7", "26.1"], dt.date(2027, 1, 2), "27.1"),  # new year starts over
        (["v1.0", "0.1.0", "26.1"], D, "26.2"),  # unrelated tags are ignored
    ],
)
def test_next_version(tags, today, expected):
    assert release.next_version(tags, today) == expected


@pytest.mark.parametrize(
    ("tags", "pre", "expected"),
    [
        ([], True, "26.1a1"),  # the very first release is an alpha
        (["26.1a1"], True, "26.1a2"),
        (["26.1a1", "26.1a2"], False, "26.1"),  # a final finishes the alpha line
        (["26.1a1", "26.1"], True, "26.2a1"),
        (["26.1a1", "26.1"], False, "26.2"),
        (["26.1", "26.2a1"], False, "26.2"),
        (["26.1a9", "26.1a10"], True, "26.1a11"),  # numeric, not lexical
    ],
)
def test_next_version_prereleases(tags, pre, expected):
    assert release.next_version(tags, D, pre=pre) == expected


def test_is_prerelease():
    assert release.is_prerelease("26.1a1")
    assert not release.is_prerelease("26.1")


def test_previous_version():
    tags = ["25.9", "26.1", "26.2", "26.10"]
    assert release.previous_version(tags, "26.11") == "26.10"
    assert release.previous_version(tags, "26.1") == "25.9"
    assert release.previous_version([], "26.1") is None
    alphas = ["26.1a1", "26.1a2"]
    assert release.previous_version(alphas, "26.1") == "26.1a2"  # the final's notes cover the last alpha
    assert release.previous_version(alphas, "26.1a2") == "26.1a1"
    assert release.previous_version(alphas, "26.1a1") is None


GENERATED = """## What's Changed
### ✨ Features
* Add threads by @alice in https://github.com/o/r/pull/1
### 🐛 Fixes
* Fix chords by @bob in https://github.com/o/r/pull/2

## New Contributors
* @bob made their first contribution in https://github.com/o/r/pull/2

**Full Changelog**: https://github.com/o/r/compare/26.1...26.2"""

CHANGELOG = """# Changelog

Intro.

## Unreleased

- A hand-written highlight.

## [26.1](https://github.com/o/r/releases/tag/26.1) - 2026-01-05

Old notes.
"""


def test_render_and_insert_section():
    highlights, emptied = release.split_unreleased(CHANGELOG)
    assert highlights == "- A hand-written highlight."
    section = release.render_section("26.2", D, "o/r", GENERATED, ["alice", "bob"], highlights)
    assert section.startswith("## [26.2](https://github.com/o/r/releases/tag/26.2) - 2026-10-08")
    assert "### Highlights\n\n- A hand-written highlight." in section
    assert "### What's Changed" in section and "#### ✨ Features" in section  # demoted one level
    assert "Thank you to everyone who contributed to this release: @alice, @bob" in section

    updated = release.insert_section(emptied, section)
    assert updated.index("## Unreleased") < updated.index("## [26.2]") < updated.index("## [26.1]")
    assert "A hand-written highlight" not in updated.split("## [26.2]")[0]  # moved, not duplicated
    assert release.extract_section(updated, "26.2").startswith("### Highlights")
    assert release.extract_section(updated, "26.1") == "Old notes.\n"
    with pytest.raises(SystemExit):
        release.extract_section(updated, "26.9")


def test_contributors_from_commits_dedupes_and_skips_bots():
    commits = [
        {"author": {"login": "alice"}, "commit": {"message": "x"}},
        {"author": {"login": "dependabot[bot]"}, "commit": {"message": "bump"}},
        {"author": None, "committer": {"login": "bob"}, "commit": {"message": "y"}},
        {
            "author": {"login": "alice"},
            "commit": {"message": "pair\n\nCo-authored-by: Carol <123+carol@users.noreply.github.com>"},
        },
    ]
    assert release.contributors_from_commits(commits) == ["alice", "bob", "carol"]


def test_set_version():
    assert 'version = "26.2"' in release.set_version('[project]\nname = "x"\nversion = "26.1"\n', "26.2")


def test_repository_changelog_and_version_agree():
    """CHANGELOG.md parses and pyproject's version is a valid CalVer version."""
    root = Path(__file__).parent.parent
    version = release.re.search(r'^version = "([^"]+)"', (root / "pyproject.toml").read_text(), release.re.M)[1]
    assert release.VERSION_RE.match(version)
    highlights, _ = release.split_unreleased((root / "CHANGELOG.md").read_text())
    assert highlights or release.extract_section((root / "CHANGELOG.md").read_text(), version)


def test_commit_notes_stand_in_for_prs():
    assert release.has_pr_entries("## What's Changed\n* Retry Redis by @a in https://x/pull/3")
    assert not release.has_pr_entries("**Full Changelog**: https://x/compare/26.1...26.2")
    assert release.commit_notes(
        ["Retry Redis connections", "Release 26.1a2", "", "Open the shell with tui --shell"]
    ) == ("## Changes\n\n* Retry Redis connections\n* Open the shell with tui --shell")
    assert release.commit_notes(["Release 26.2"]) == ""


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A checkout of main with an "origin", a 26.1 tag and one commit since."""
    import subprocess

    def git(*args, cwd):
        subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@e", *args], cwd=cwd, check=True,
                       capture_output=True)  # fmt: skip

    # Leave the developer's git config (signing, hooks, default branch) out of it.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    git("init", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    git("clone", str(origin), str(work), cwd=tmp_path)
    (work / "CHANGELOG.md").write_text(CHANGELOG)
    (work / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "26.1"\n')
    (work / "uv.lock").write_text("version = 1\n")
    git("add", ".", cwd=work)
    git("commit", "-m", "Release 26.1", cwd=work)
    git("tag", "26.1", cwd=work)
    git("commit", "--allow-empty", "-m", "Retry Redis connections", cwd=work)
    git("push", "origin", "main", "--tags", cwd=work)
    monkeypatch.setattr(release, "ROOT", work)
    monkeypatch.setattr(release, "CHANGELOG", work / "CHANGELOG.md")
    monkeypatch.setattr(release, "PYPROJECT", work / "pyproject.toml")
    monkeypatch.setattr(release, "generated_notes", lambda *a: "**Full Changelog**: https://x/compare")
    monkeypatch.setattr(release, "release_contributors", lambda *a: ["alice"])
    real_run = release.run
    monkeypatch.setattr(release, "run", lambda *cmd, **kw: "" if cmd[:2] == ("uv", "lock") else real_run(*cmd, **kw))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "T")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@e")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "T")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@e")
    return work


def test_prepare_commits_the_release_on_main(repo, capsys):
    release.main(["prepare", "--repo", "o/r"])
    assert release.run("git", "log", "-1", "--format=%s") == "Release 26.2"
    changelog = (repo / "CHANGELOG.md").read_text()
    assert "## [26.2](https://github.com/o/r/releases/tag/26.2)" in changelog
    assert "* Retry Redis connections" in changelog  # no PRs: the commits since 26.1
    assert 'version = "26.2"' in (repo / "pyproject.toml").read_text()
    assert "Push it to publish" in capsys.readouterr().out
    assert release.run("git", "rev-list", "--count", "origin/main..HEAD").strip() == "1"  # not pushed


def test_prepare_push_publishes_to_origin_and_waits(repo, capsys, monkeypatch):
    waited = []
    monkeypatch.setattr(release, "wait_for_release", lambda *args: waited.append(args))
    release.main(["prepare", "--repo", "o/r", "--pre", "--push"])
    assert release.run("git", "log", "-1", "--format=%s", "origin/main") == "Release 26.2a1"
    assert "Pushed." in capsys.readouterr().out
    assert waited == [("o/r", release.run("git", "rev-parse", "HEAD"), "26.2a1")]


def test_prepare_push_no_wait(repo, monkeypatch):
    monkeypatch.setattr(release, "wait_for_release", lambda *args: pytest.fail("waited"))
    release.main(["prepare", "--repo", "o/r", "--pre", "--push", "--no-wait"])
    assert release.run("git", "log", "-1", "--format=%s", "origin/main") == "Release 26.2a1"


@pytest.fixture
def actions(monkeypatch):
    """Fake GitHub Actions: runs appear after a poll; ``results`` decides how they end."""
    state = {"polls": 0, "results": {"ci.yml": True, "release.yml": True}, "watched": []}

    def gh_json(*args):
        workflow = args[args.index("--workflow") + 1]
        state["polls"] += 1
        if state["polls"] == 1:
            return []  # GitHub hasn't created the run yet
        return [{"databaseId": workflow, "url": f"https://x/{workflow}"}]

    def watch_run(repo, run_id):
        state["watched"].append(run_id)
        result = state["results"][run_id]
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(release, "gh_json", gh_json)
    monkeypatch.setattr(release, "watch_run", watch_run)
    monkeypatch.setattr(release.time, "sleep", lambda s: None)
    return state


def test_wait_reports_the_release(actions, capsys):
    release.wait_for_release("o/r", "abc1234def", "26.2a1")
    assert actions["watched"] == ["ci.yml", "release.yml"]
    out = capsys.readouterr().out
    assert "✅ Released 26.2a1" in out
    assert "https://pypi.org/project/django-tui/26.2a1/" in out
    assert "https://github.com/o/r/releases/tag/26.2a1" in out


def test_wait_reports_failures(actions):
    actions["results"]["ci.yml"] = False
    with pytest.raises(SystemExit, match=re.escape("CI failed, so 26.2a1 wasn't published: https://x/ci.yml")):
        release.wait_for_release("o/r", "abc1234def", "26.2a1")
    assert actions["watched"] == ["ci.yml"]  # nothing to wait for after a red CI
    actions["results"]["ci.yml"] = True
    actions["results"]["release.yml"] = False
    with pytest.raises(SystemExit, match=re.escape("Publishing 26.2a1 failed: https://x/release.yml")):
        release.wait_for_release("o/r", "abc1234def", "26.2a1")
    actions["results"]["ci.yml"] = KeyboardInterrupt()
    with pytest.raises(SystemExit, match="Stopped waiting"):
        release.wait_for_release("o/r", "abc1234def", "26.2a1")


def test_wait_gives_up_when_no_run_shows_up(monkeypatch):
    monkeypatch.setattr(release, "gh_json", lambda *args: [])
    monkeypatch.setattr(release.time, "sleep", lambda s: None)
    with pytest.raises(SystemExit, match=re.escape("No ci.yml run for abc1234 showed up")):
        release.find_run("o/r", "ci.yml", "abc1234def", timeout=0)


def test_wait_command_reads_the_version_of_the_commit(repo, monkeypatch):
    waited = []
    monkeypatch.setattr(release, "wait_for_release", lambda *args: waited.append(args))
    release.main(["wait", "--repo", "o/r"])
    assert waited == [("o/r", release.run("git", "rev-parse", "HEAD"), "26.1")]


def test_prepare_refuses_unless_main_is_clean_and_current(repo):
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "26.1"\n# edited\n')
    with pytest.raises(SystemExit, match="Commit or stash"):
        release.main(["prepare", "--repo", "o/r"])
    release.run("git", "checkout", "pyproject.toml")
    release.run("git", "switch", "-c", "feature")
    with pytest.raises(SystemExit, match="Switch to main first"):
        release.main(["prepare", "--repo", "o/r"])
    release.run("git", "switch", "main")
    release.run("git", "reset", "--hard", "HEAD~1")  # origin/main is now ahead
    with pytest.raises(SystemExit, match="behind origin/main"):
        release.main(["prepare", "--repo", "o/r"])

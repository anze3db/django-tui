"""Release tooling: CalVer versions, changelog generation, release commits.

    uv run scripts/release.py prepare            # commit "Release 26.N", push it, wait for CI and the release
    uv run scripts/release.py prepare --no-wait  # ... and don't wait
    uv run scripts/release.py wait               # wait for the release of a pushed HEAD
    uv run scripts/release.py prepare --pre      # an alpha instead: 26.3a1, 26.3a2, ...
    uv run scripts/release.py prepare --dry-run  # print the changelog section, change nothing
    uv run scripts/release.py prepare --pr       # open a "Release 26.N" PR instead (needs `gh`)
    uv run scripts/release.py next-version       # e.g. 26.3
    uv run scripts/release.py notes 26.2         # the CHANGELOG.md section for a release

Versions are CalVer ``YY.N``: the Nth release of the year (26.1, 26.2, ... 27.1).
Alphas are PEP 440 pre-releases of the upcoming number: 26.1a1, 26.1a2, then 26.1.

Release notes come from GitHub's generator: merged PR titles grouped by label
(.github/release.yml), new contributors and a compare link. Changes pushed straight to
main have no PR, so when there are none the commit messages since the last release
are listed instead. This script adds the full list of everyone who contributed to the
release, any hand-written notes from the "Unreleased" section of CHANGELOG.md, and
writes it all into CHANGELOG.md. The same text becomes the GitHub release body.

Pushing the release commit to main publishes it, once CI has passed on that commit
(.github/workflows/release.yml).

Standard library only, so it runs anywhere `gh` is installed and authenticated. It only
uses GitHub's REST API (`gh api`, `gh run`): some environments block GraphQL.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
PYPROJECT = ROOT / "pyproject.toml"
PACKAGE = tomllib.loads(PYPROJECT.read_text())["project"]["name"]
#: YY.N, optionally a pre-release YY.NaM (PEP 440 alpha: 26.1a1, 26.1a2, then 26.1).
VERSION_RE = re.compile(r"^(\d{2})\.(\d+)(?:a(\d+))?$")
RELEASE_COMMIT_RE = re.compile(r"^Release \d{2}\.\d+(a\d+)?$")
BOTS = re.compile(r"(\[bot\]$|^dependabot|^github-actions|^renovate)", re.IGNORECASE)


# --- pure functions (unit tested) -------------------------------------------------


def _key(version: str) -> tuple[int, int, float]:
    """Sort key: 26.1a1 < 26.1a2 < 26.1 < 26.2a1 < 26.2."""
    m = VERSION_RE.match(version)
    if not m:
        return (-1, -1, -1)
    return (int(m[1]), int(m[2]), int(m[3]) if m[3] else float("inf"))


def is_prerelease(version: str) -> bool:
    m = VERSION_RE.match(version)
    return bool(m and m[3])


def next_version(existing: list[str], today: dt.date, pre: bool = False) -> str:
    """The next CalVer version after ``existing`` tags/versions for ``today``'s year.

    ``pre=True`` gives the next alpha: ``26.1a1``, ``26.1a2``, ... A final release after
    alphas finishes that line (``26.1a2`` -> ``26.1``)."""
    year = today.year % 100
    versions = [k for k in map(_key, existing) if k[0] == year]
    final = max((n for _, n, a in versions if a == float("inf")), default=0)
    pending = [(n, int(a)) for _, n, a in versions if a != float("inf") and n > final]
    if pending:
        number, alpha = max(pending)
        return f"{year}.{number}a{alpha + 1}" if pre else f"{year}.{number}"
    return f"{year}.{final + 1}a1" if pre else f"{year}.{final + 1}"


def previous_version(existing: list[str], version: str) -> str | None:
    """The newest release before ``version`` (None for the very first release)."""
    older = [v for v in existing if VERSION_RE.match(v) and _key(v) < _key(version)]
    return max(older, key=_key) if older else None


def demote_headings(markdown: str, levels: int = 1) -> str:
    """GitHub's generated notes use ``##``; inside a ``## 26.2`` section they go one deeper."""
    out = []
    in_code = False
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
        if not in_code and re.match(r"^#{1,5} ", line):
            line = "#" * levels + line
        out.append(line)
    return "\n".join(out)


def split_unreleased(changelog: str) -> tuple[str, str]:
    """Return (hand-written "Unreleased" notes, changelog with that section emptied)."""
    m = re.search(r"^## Unreleased[^\n]*\n(.*?)(?=^## |\Z)", changelog, flags=re.MULTILINE | re.DOTALL)
    if not m:
        return "", changelog
    notes = m.group(1).strip()
    emptied = changelog[: m.start(1)] + "\n" + changelog[m.end(1) :]
    return notes, emptied


def render_section(
    version: str,
    date: dt.date,
    repo: str,
    generated: str,
    contributors: list[str],
    highlights: str = "",
) -> str:
    parts = [f"## [{version}](https://github.com/{repo}/releases/tag/{version}) - {date.isoformat()}", ""]
    if highlights:
        parts += ["### Highlights", "", highlights, ""]
    body = demote_headings(generated.strip())
    if body:
        parts += [body, ""]
    if contributors:
        people = ", ".join(f"@{login}" for login in contributors)
        parts += ["### Contributors", "", f"Thank you to everyone who contributed to this release: {people}", ""]
    return "\n".join(parts).rstrip() + "\n"


def insert_section(changelog: str, section: str) -> str:
    """Insert ``section`` above the newest release (below "Unreleased" if present)."""
    m = re.search(r"^## (?!Unreleased)", changelog, flags=re.MULTILINE)
    if m is None:
        return changelog.rstrip() + "\n\n" + section
    return changelog[: m.start()] + section + "\n" + changelog[m.start() :]


def extract_section(changelog: str, version: str) -> str:
    """The body of a release's section (what goes into the GitHub release)."""
    m = re.search(rf"^## \[?{re.escape(version)}\]?[^\n]*\n(.*?)(?=^## |\Z)", changelog, flags=re.MULTILINE | re.DOTALL)
    if not m:
        raise SystemExit(f"CHANGELOG.md has no section for {version}")
    return m.group(1).strip() + "\n"


def set_version(pyproject: str, version: str) -> str:
    new, n = re.subn(r'^version = "[^"]*"', f'version = "{version}"', pyproject, count=1, flags=re.MULTILINE)
    if n != 1:
        raise SystemExit("No version in pyproject.toml")
    return new


def contributors_from_commits(commits: list[dict]) -> list[str]:
    """Unique GitHub logins of commit authors (bots excluded), in order of first appearance."""
    seen: dict[str, None] = {}
    for commit in commits:
        for who in (commit.get("author"), commit.get("committer")):
            login = (who or {}).get("login")
            if login and not BOTS.search(login) and login != "web-flow":
                seen.setdefault(login, None)
                break
        for line in (commit.get("commit", {}).get("message") or "").splitlines():
            # Co-authored-by: Name <123+login@users.noreply.github.com>
            m = re.match(
                r"co-authored-by:.*<(?:\d+\+)?([^@<>]+)@users\.noreply\.github\.com>", line.strip(), re.IGNORECASE
            )
            if m and not BOTS.search(m[1]):
                seen.setdefault(m[1], None)
    return list(seen)


# --- GitHub / git plumbing ------------------------------------------------------


def run(*cmd: str, capture: bool = True) -> str:
    result = subprocess.run(cmd, cwd=ROOT, check=True, text=True, capture_output=capture)
    return result.stdout.strip() if capture else ""


def gh_json(*args: str) -> object:
    return json.loads(run("gh", *args))


def repo_from_url(url: str) -> str | None:
    """``owner/name`` from a remote URL: https, ssh, or a proxy that keeps the path."""
    m = re.search(r"[/:]([^/:]+/[^/]+?)(?:\.git)?/?$", url)
    return m[1] if m else None


def repo_name() -> str:
    """The origin remote's repository (not `gh repo view`, which needs GraphQL)."""
    url = run("git", "remote", "get-url", "origin")
    repo = repo_from_url(url)
    if not repo:
        raise SystemExit(f"Can't tell the GitHub repository from origin ({url}): pass --repo owner/name")
    return repo


def has_pr_entries(generated: str) -> bool:
    """Whether GitHub's generated notes list any pull requests (``* Title by @x in #12``)."""
    return any(line.lstrip().startswith(("* ", "- ")) for line in generated.splitlines())


def commit_notes(subjects: list[str]) -> str:
    """A "Changes" list from commit subjects, without the release commits themselves."""
    items = [s for s in subjects if s.strip() and not RELEASE_COMMIT_RE.match(s)]
    if not items:
        return ""
    return "## Changes\n\n" + "\n".join(f"* {s}" for s in items)


def commit_subjects(previous: str | None, target: str) -> list[str]:
    span = f"{previous}..{target}" if previous else target
    return run("git", "log", "--no-merges", "--reverse", "--format=%s", span).splitlines()


def release_tags() -> list[str]:
    run("git", "fetch", "--tags", "--quiet")
    return [t for t in run("git", "tag", "--list").split() if VERSION_RE.match(t)]


def generated_notes(repo: str, version: str, previous: str | None, target: str) -> str:
    args = [
        "api", "-X", "POST", f"repos/{repo}/releases/generate-notes",
        "-f", f"tag_name={version}", "-f", f"target_commitish={target}",
        "-f", "configuration_file_path=.github/release.yml",
    ]  # fmt: skip
    if previous:
        args += ["-f", f"previous_tag_name={previous}"]
    return str(gh_json(*args)["body"])  # type: ignore[index]


def release_contributors(repo: str, previous: str | None, target: str) -> list[str]:
    if previous:
        pages = gh_json("api", "--paginate", "--slurp", f"repos/{repo}/compare/{previous}...{target}")
        commits = [c for page in pages for c in page["commits"]]  # type: ignore[union-attr]
    else:
        pages = gh_json("api", "--paginate", "--slurp", f"repos/{repo}/commits?sha={target}&per_page=100")
        commits = [c for page in pages for c in page]  # type: ignore[union-attr]
    return contributors_from_commits(commits)


# --- commands ---------------------------------------------------------------------


def find_run(repo: str, workflow: str, sha: str, timeout: float = 300.0) -> dict:
    """The newest run of ``workflow`` for commit ``sha``, once GitHub has created it."""
    deadline = time.monotonic() + timeout
    while True:
        runs = gh_json(
            "run", "list", "--repo", repo, "--workflow", workflow, "--commit", sha,
            "--limit", "1", "--json", "databaseId,url",
        )  # fmt: skip
        if runs:
            return runs[0]  # type: ignore[index]
        if time.monotonic() > deadline:
            raise SystemExit(f"No {workflow} run for {sha[:7]} showed up: https://github.com/{repo}/actions")
        time.sleep(5)


def watch_run(repo: str, run_id: int) -> bool:
    """Follow a run in the terminal until it finishes; True if it succeeded."""
    cmd = ["gh", "run", "watch", str(run_id), "--repo", repo, "--compact", "--exit-status", "--interval", "10"]
    return subprocess.run(cmd, check=False, cwd=ROOT).returncode == 0


def wait_for_release(repo: str, sha: str, version: str) -> None:
    """Wait for CI on the pushed release commit, then for the Release workflow."""
    print(f"Waiting for CI on {sha[:7]}; Ctrl+C stops waiting, the release goes ahead anyway.", flush=True)
    try:
        ci = find_run(repo, "ci.yml", sha)
        if not watch_run(repo, ci["databaseId"]):
            raise SystemExit(
                f"\n❌ CI failed, so {version} wasn't published: {ci['url']}\n"
                f"Fix it and push again: the next green run on main releases {version}."
            )
        published = find_run(repo, "release.yml", sha)
        if not watch_run(repo, published["databaseId"]):
            raise SystemExit(
                f"\n❌ Publishing {version} failed: {published['url']}\n"
                "Once fixed, re-run it: Actions → Release → Run workflow."
            )
    except KeyboardInterrupt:
        raise SystemExit(f"\nStopped waiting. Follow it at https://github.com/{repo}/actions") from None
    print(f"\n✅ Released {version}")
    print(f"   https://pypi.org/project/{PACKAGE}/{version}/")
    print(f"   https://github.com/{repo}/releases/tag/{version}")


def check_releasable(target: str) -> None:
    """A release commit goes on top of the target branch as everyone else sees it."""
    branch = run("git", "branch", "--show-current").strip()
    if branch != target:
        raise SystemExit(f"Switch to {target} first (you're on {branch or 'a detached HEAD'})")
    if run("git", "status", "--porcelain", "--untracked-files=no").strip():
        raise SystemExit("Commit or stash your changes first: the release commit should only bump the version")
    run("git", "fetch", "--quiet", "origin", target)
    if run("git", "rev-list", "--count", f"HEAD..origin/{target}").strip() != "0":
        raise SystemExit(f"Your {target} is behind origin/{target}: pull first")


def cmd_next_version(args: argparse.Namespace) -> None:
    print(next_version(release_tags(), dt.date.today(), pre=args.pre))


def cmd_notes(args: argparse.Namespace) -> None:
    sys.stdout.write(extract_section(CHANGELOG.read_text(), args.version))


def cmd_wait(args: argparse.Namespace) -> None:
    sha = run("git", "rev-parse", args.commit)
    version = args.version or tomllib.loads(run("git", "show", f"{sha}:pyproject.toml"))["project"]["version"]
    wait_for_release(args.repo or repo_name(), sha, version)


def cmd_prepare(args: argparse.Namespace) -> None:
    repo = args.repo or repo_name()
    tags = release_tags()
    version = args.version or next_version(tags, dt.date.today(), pre=args.pre)
    if not VERSION_RE.match(version):
        raise SystemExit(f"{version!r} isn't a CalVer version (YY.N or YY.NaM)")
    if version in tags:
        raise SystemExit(f"{version} is already released")
    previous = previous_version(tags, version)
    target = args.target
    if not args.pr and not args.dry_run:
        check_releasable(target)
    changelog = CHANGELOG.read_text()
    highlights, changelog = split_unreleased(changelog)
    generated = generated_notes(repo, version, previous, target)
    if not has_pr_entries(generated):
        # Pushed straight to main: list the commits instead of (nonexistent) PRs.
        changes = commit_notes(commit_subjects(previous, f"origin/{target}" if args.from_remote else "HEAD"))
        generated = f"{changes}\n\n{generated}".strip() if changes else generated
    section = render_section(
        version,
        dt.date.today(),
        repo,
        generated,
        release_contributors(repo, previous, target),
        highlights,
    )
    if args.dry_run:
        print(f"# Would release {version} (previous: {previous or 'none'})\n")
        print(section)
        return
    if args.pr:
        run(
            "git",
            "switch",
            "-c",
            f"release/{version}",
            f"origin/{target}" if args.from_remote else target,
            capture=False,
        )
    CHANGELOG.write_text(insert_section(changelog, section))
    PYPROJECT.write_text(set_version(PYPROJECT.read_text(), version))
    run("uv", "lock", capture=False)
    run("git", "add", "CHANGELOG.md", "pyproject.toml", "uv.lock")
    run("git", "commit", "-m", f"Release {version}", capture=False)
    if not args.pr:
        run("git", "push", "origin", f"HEAD:{target}", capture=False)
        print(f"Pushed. {version} is published once CI passes on it (Actions → Release).")
        if not args.no_wait:
            wait_for_release(repo, run("git", "rev-parse", "HEAD"), version)
        return
    run("git", "push", "-u", "origin", f"release/{version}", capture=False)
    body = (
        f"Merging this PR publishes **{version}** to PyPI and creates the GitHub release "
        f"(.github/workflows/release.yml).\n\n---\n\n{section}"
    )
    # The REST API rather than `gh pr create`, which needs GraphQL.
    pr = gh_json(
        "api", "-X", "POST", f"repos/{repo}/pulls", "-f", f"title=Release {version}",
        "-f", f"head=release/{version}", "-f", f"base={target}", "-f", f"body={body}",
    )  # fmt: skip
    number, url = pr["number"], pr["html_url"]  # type: ignore[index]
    gh_json("api", "-X", "POST", f"repos/{repo}/issues/{number}/labels", "-f", "labels[]=release")
    print(f"Opened {url}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="Bump the version, write CHANGELOG.md, commit and push the release")
    p.add_argument("--version", help="Override the computed CalVer version")
    p.add_argument("--target", default="main", help="Branch to release from")
    p.add_argument("--repo", help="owner/name (default: from the origin remote)")
    p.add_argument("--from-remote", action="store_true", help="Branch off origin/<target> (CI)")
    p.add_argument("--pre", action="store_true", help="Release the next alpha (e.g. 26.2a1) instead of a final")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-wait", action="store_true", help="Push, but don't wait for CI and the release")
    p.add_argument("--pr", action="store_true", help="Open a release PR instead of committing to the branch")
    p.set_defaults(func=cmd_prepare)
    nv = sub.add_parser("next-version")
    nv.add_argument("--pre", action="store_true")
    nv.set_defaults(func=cmd_next_version)
    w = sub.add_parser("wait", help="Wait for CI and the release of a pushed commit")
    w.add_argument("commit", nargs="?", default="HEAD")
    w.add_argument("--version", help="Default: the version in that commit's pyproject.toml")
    w.add_argument("--repo", help="owner/name (default: from the origin remote)")
    w.set_defaults(func=cmd_wait)
    n = sub.add_parser("notes")
    n.add_argument("version")
    n.set_defaults(func=cmd_notes)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

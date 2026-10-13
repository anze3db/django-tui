"""Takes the README's screenshots of the test project: `just screenshots`.

Textual saves each screenshot as an SVG, which headless Chrome turns into a PNG at twice the size, so it stays sharp.
Set CHROME to Chrome's (or Chromium's) path if it isn't found.

Images go in docs/images/<next version>/ and the README links to them there. PyPI shows each release's README with
the images of that release, so never delete old images: new ones get a new directory.

    uv run python docs/screenshots.py                     # take the screenshots
    uv run python docs/screenshots.py --version-dir       # print the directory for the next version's images
    uv run python docs/screenshots.py --readme demo.gif   # point the README at the next version's demo.gif
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "docs" / "images"
README = ROOT / "README.md"

# name: (width, height, open the shell, keys to press)
SCREENSHOTS = {
    "commands": (110, 26, False, ["type:closepoll 1 2 --delete"]),
    "shell": (110, 20, True, ["type:Question.objects.filter(is_open=True", "ctrl+r"]),
}


def version_dir() -> Path:
    """The directory for the images of the next release, e.g. docs/images/26.2."""
    spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
    release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release)
    return IMAGES / release.next_version(release.release_tags(), dt.date.today())


def point_readme_at(image: Path) -> None:
    """Link the README to this image instead of an older one with the same name."""
    relative = image.relative_to(ROOT).as_posix()
    pattern = rf"docs/images/[^/\s)]+/{re.escape(image.name)}"
    readme, count = re.subn(pattern, relative, README.read_text())
    if not count:
        raise SystemExit(f"README.md doesn't show {image.name}")
    README.write_text(readme)


def find_chrome() -> str:
    candidates = [
        os.environ.get("CHROME", ""),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        *(shutil.which(name) or "" for name in ("google-chrome", "chromium", "chromium-browser")),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise SystemExit("Chrome not found: set CHROME to its path")


def svg_to_png(svg: Path, png: Path, chrome: str) -> None:
    width, height = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg.read_text()).groups()
    subprocess.run(
        [
            chrome,
            "--headless=new",
            "--hide-scrollbars",
            "--force-device-scale-factor=2",
            f"--window-size={int(float(width)) + 1},{int(float(height)) + 1}",
            f"--screenshot={png}",
            svg.as_uri(),
        ],
        check=True,
        capture_output=True,
    )


async def take(name: str, width: int, height: int, shell: bool, keys: list[str], directory: Path) -> Path:
    from django_tui.app import DjangoTui

    app = DjangoTui(open_shell=shell)
    async with app.run_test(size=(width, height)) as pilot:
        await pilot.pause(0.3)
        for key in keys:
            if key.startswith("type:"):
                await pilot.press(*key.removeprefix("type:"))
            else:
                await pilot.press(key)
        await pilot.pause(0.5)
        return Path(app.save_screenshot(f"{name}.svg", path=str(directory)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version-dir", action="store_true", help="Print the directory for the next version's images")
    parser.add_argument("--readme", metavar="IMAGE", help="Point the README at the next version's IMAGE")
    args = parser.parse_args()
    directory = version_dir()
    if args.version_dir:
        print(directory.relative_to(ROOT).as_posix())
        return
    if args.readme:
        point_readme_at(directory / args.readme)
        return

    chrome = find_chrome()
    os.chdir(ROOT / "tests")
    sys.path.insert(0, str(ROOT / "tests"))
    sys.argv = ["manage.py", "tui"]
    os.environ["DJANGO_SETTINGS_MODULE"] = "testapp.settings"
    subprocess.run([sys.executable, "manage.py", "migrate", "-v0"], check=True)
    subprocess.run([sys.executable, "manage.py", "flush", "--noinput", "-v0"], check=True)
    subprocess.run([sys.executable, "manage.py", "loaddata", "demo", "-v0"], check=True)

    import django

    django.setup()
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as svgs:
        for name, (width, height, shell, keys) in SCREENSHOTS.items():
            png = directory / f"{name}.png"
            svg_to_png(asyncio.run(take(name, width, height, shell, keys, Path(svgs))), png, chrome)
            point_readme_at(png)
            print(png.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()

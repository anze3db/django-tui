"""Takes the README's screenshots of the test project: `just screenshots`.

Textual saves each screenshot as an SVG, which headless Chrome turns into a PNG at twice the size, so it stays sharp.
Set CHROME to Chrome's (or Chromium's) path if it isn't found.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "docs" / "images"

# name: (width, height, open the shell, keys to press)
SCREENSHOTS = {
    "commands": (110, 26, False, ["type:closepoll 1 2 --delete"]),
    "shell": (110, 20, True, ["type:Question.objects.filter(is_open=True", "ctrl+r"]),
}


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
    with tempfile.TemporaryDirectory() as directory:
        for name, (width, height, shell, keys) in SCREENSHOTS.items():
            svg = asyncio.run(take(name, width, height, shell, keys, Path(directory)))
            svg_to_png(svg, IMAGES / f"{name}.png", chrome)
            print(f"docs/images/{name}.png")


if __name__ == "__main__":
    main()

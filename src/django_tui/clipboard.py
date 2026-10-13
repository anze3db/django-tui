from __future__ import annotations

import shutil
import subprocess
import sys

from textual.app import App

if sys.platform == "darwin":
    COPY_COMMANDS = [["pbcopy"]]
elif sys.platform == "win32":
    COPY_COMMANDS = [["clip"]]
else:
    COPY_COMMANDS = [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]


def copy_to_clipboard(app: App, text: str) -> None:
    # Textual copies with an escape sequence (OSC 52), which some terminals ignore, e.g. macOS Terminal.app.
    # Also use the system clipboard tool when one is available.
    app.copy_to_clipboard(text)
    for command in COPY_COMMANDS:
        if shutil.which(command[0]):
            subprocess.run(command, input=text, text=True, check=False, capture_output=True)
            return

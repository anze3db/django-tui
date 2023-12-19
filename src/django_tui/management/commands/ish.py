from __future__ import annotations

import importlib
import os
import platform
import sys
import traceback
import warnings
from functools import lru_cache
from io import StringIO
from subprocess import run
from typing import List, Tuple

import django
from django.apps import apps
from rich.syntax import Syntax
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import HorizontalScroll, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Footer,
    Label,
    MarkdownViewer,
    TextArea,
)
from textual.widgets.text_area import Location, Selection

DEFAULT_IMPORT = {
    "rich": ["print_json", "print"],
    "django.db.models": [
        "Avg",
        "Case",
        "Count",
        "F",
        "Max",
        "Min",
        "Prefetch",
        "Q",
        "Sum",
        "When",
    ],
    "django.conf": [
        "settings",
    ],
    "django.core.cache": [
        "cache",
    ],
    "django.contrib.auth": [
        "get_user_model",
    ],
    "django.utils": [
        "timezone",
    ],
    "django.urls": ["reverse"],
}


@lru_cache
def get_modules():
    """
    Return list of modules and symbols to import
    """
    mods = {}
    for module_name, symbols in DEFAULT_IMPORT.items():
        try:
            module = importlib.import_module(module_name)
        except ImportError as e:
            warnings.warn("django_admin_shell - autoimport warning :: {msg}".format(msg=str(e)), ImportWarning)
            continue

        mods[module_name] = []
        for symbol_name in symbols:
            if hasattr(module, symbol_name):
                mods[module_name].append(symbol_name)
            else:
                warnings.warn(
                    "django_admin_shell - autoimport warning :: "
                    "AttributeError module '{mod}' has no attribute '{attr}'".format(mod=module_name, attr=symbol_name),
                    ImportWarning,
                )

    for model_class in apps.get_models():
        _mod = model_class.__module__
        classes = mods.get(_mod, [])
        classes.append(model_class.__name__)
        mods[_mod] = classes

    return mods


@lru_cache
def get_scope():
    """
    Return map with symbols to module/object
    Like:
    "reverse" -> "django.urls.reverse"
    """
    scope = {}
    for module_name, symbols in get_modules().items():
        module = importlib.import_module(module_name)
        for symbol_name in symbols:
            scope[symbol_name] = getattr(module, symbol_name)
    return scope


@lru_cache
def import_str():
    buf = []
    for module, symbols in get_modules().items():
        if symbols:
            buf.append(f"from {module} import {', '.join(symbols)}")
    return "\n".join(buf)


def run_code(code):
    """
    Execute code and return result with status = success|error
    Function manipulate stdout to grab output from exec
    """
    status = "success"
    out = ""
    tmp_stdout = sys.stdout
    buf = StringIO()

    try:
        sys.stdout = buf
        exec(code, None, get_scope())
    except Exception:
        out = traceback.format_exc()
        status = "error"
    else:
        out = buf.getvalue()
    finally:
        sys.stdout = tmp_stdout

    result = {
        "code": code,
        "out": out,
        "status": status,
    }
    return result


class ExtendedTextArea(TextArea):
    """A subclass of TextArea with parenthesis-closing functionality."""

    def _on_key(self, event: events.Key) -> None:
        if event.character == "(":
            self.insert("()")
            self.move_cursor_relative(columns=-1)
            event.prevent_default()

        if event.character == "[":
            self.insert("[]")
            self.move_cursor_relative(columns=-1)
            event.prevent_default()

        if event.character == "{":
            self.insert("{}")
            self.move_cursor_relative(columns=-1)
            event.prevent_default()

        if event.character == '"':
            self.insert('""')
            self.move_cursor_relative(columns=-1)
            event.prevent_default()

        if event.character == "'":
            self.insert("''")
            self.move_cursor_relative(columns=-1)
            event.prevent_default()


class TextEditorBindingsInfo(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "dismiss(None)", "", show=False),
    ]

    DEFAULT_CSS = """
    TextEditorBindingsInfo {
        align: center middle;
    }
"""

    key_bindings = """
Text Editor Key Bindings List
| Key(s)           | Description                                          |
|------------------|------------------------------------------------------|
| escape           | Focus on the next item.                              |
| up               | Move the cursor up.                                  |
| down             | Move the cursor down.                                |
| left             | Move the cursor left.                                |
| ctrl+left        | Move the cursor to the start of the word.            |
| ctrl+shift+left  | Move the cursor to the start of the word and select. |
| right            | Move the cursor right.                               |
| ctrl+right       | Move the cursor to the end of the word.              |
| ctrl+shift+right | Move the cursor to the end of the word and select.   |
| home,ctrl+a      | Move the cursor to the start of the line.            |
| end,ctrl+e       | Move the cursor to the end of the line.              |
| shift+home       | Move the cursor to the start of the line and select. |
| shift+end        | Move the cursor to the end of the line and select.   |
| pageup           | Move the cursor one page up.                         |
| pagedown         | Move the cursor one page down.                       |
| shift+up         | Select while moving the cursor up.                   |
| shift+down       | Select while moving the cursor down.                 |
| shift+left       | Select while moving the cursor left.                 |
| shift+right      | Select while moving the cursor right.                |
| backspace        | Delete character to the left of cursor.              |
| ctrl+w           | Delete from cursor to start of the word.             |
| delete,ctrl+d    | Delete character to the right of cursor.             |
| ctrl+f           | Delete from cursor to end of the word.               |
| ctrl+x           | Delete the current line.                             |
| ctrl+u           | Delete from cursor to the start of the line.         |
| ctrl+k           | Delete from cursor to the end of the line.           |
| f6               | Select the current line.                             |
| f7               | Select all text in the document.                     |
"""
    _title = "Editor Keys Bindings"

    def compose(self) -> ComposeResult:
        """Compose the content of the modal dialog."""
        with Vertical(id="dialog"):
            yield MarkdownViewer(self.key_bindings, classes="spaced", show_table_of_contents=False)


class DefaultImportsInfo(ModalScreen[None]):
    BINDINGS = [
        Binding(
            "escape",
            "dismiss(None)",
            "Close",
        ),
    ]

    DEFAULT_CSS = """
    DefaultImportsInfo {
        align: center middle;
    }
"""

    _title = "Default Imported Modules"

    def __init__(
        self,
        imported_modules: str,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        self.imported_modules = imported_modules
        super().__init__(name, id, classes)

    def compose(self) -> ComposeResult:
        """Compose the content of the modal dialog."""
        syntax = Syntax(
            code=self.imported_modules,
            lexer="python",
            line_numbers=True,
            word_wrap=False,
            indent_guides=True,
            theme="dracula",
        )
        with VerticalScroll(id="dialog"):
            yield Label(syntax)


class InteractiveShellScreen(Screen):
    def __init__(
        self,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        super().__init__(name, id, classes)
        self.input_tarea = ExtendedTextArea("", id="input", language="python", theme="vscode_dark")
        self.output_tarea = TextArea(
            "# Output",
            id="output",
            language="python",
            theme="vscode_dark",
            classes="text-area",
        )

    BINDINGS = [
        Binding(key="ctrl+r", action="run_code", description="Run the query"),
        Binding(key="ctrl+z", action="copy_command", description="Copy to Clipboard"),
        Binding(key="f1", action="editor_keys", description="Key Bindings"),
        Binding(key="f2", action="default_imports", description="Default imports"),
        Binding(key="ctrl+j", action="select_mode('commands')", description="Commands"),
        Binding(key="ctrl+underscore", action="toggle_comment", description="Toggle Comment", show=False),
    ]

    def compose(self) -> ComposeResult:
        self.input_tarea.focus()

        yield HorizontalScroll(
            self.input_tarea,
            self.output_tarea,
        )
        yield Label(f"Python: {platform.python_version()}  Django: {django.__version__}")
        yield Footer()

    def action_default_imports(self) -> None:
        self.app.push_screen(DefaultImportsInfo(import_str()))

    def action_run_code(self) -> None:
        # get Code from start till the position of the cursor
        self.input_tarea.selection = Selection(start=(0, 0), end=self.input_tarea.cursor_location)
        self.input_tarea.action_cursor_line_end()
        code = self.input_tarea.get_text_range(start=(0, 0), end=self.input_tarea.cursor_location)

        if len(code) > 0:
            # Because the cli - texualize is running on a loop - has an event loop
            # os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rest.settings')
            os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
            django.setup()

            result = run_code(code)
            self.output_tarea.load_text(result["out"])

    def action_copy_command(self) -> None:
        if sys.platform == "win32":
            copy_command = ["clip"]
        elif sys.platform == "darwin":
            copy_command = ["pbcopy"]
        else:
            copy_command = ["xclip", "-selection", "clipboard"]

        try:
            text_to_copy = self.input_tarea.selected_text

            run(
                copy_command,
                input=text_to_copy,
                text=True,
                check=False,
            )
            self.notify("Selction copied to clipboard.")
        except FileNotFoundError:
            self.notify(f"Could not copy to clipboard. `{copy_command[0]}` not found.", severity="error")

    def _get_selected_lines(self) -> Tuple[List[str], Location, Location]:
        [first, last] = sorted([self.input_tarea.selection.start, self.input_tarea.selection.end])
        lines = [self.input_tarea.document.get_line(i) for i in range(first[0], last[0] + 1)]
        return lines, first, last

    def action_toggle_comment(self) -> None:
        inline_comment_marker = "#"

        if inline_comment_marker:
            lines, first, last = self._get_selected_lines()
            stripped_lines = [line.lstrip() for line in lines]
            indents = [len(line) - len(line.lstrip()) for line in lines]
            # if lines are already commented, remove them
            if lines and all(not line or line.startswith(inline_comment_marker) for line in stripped_lines):
                offsets = [
                    0 if not line else (2 if line[len(inline_comment_marker)].isspace() else 1)
                    for line in stripped_lines
                ]
                for lno, indent, offset in zip(range(first[0], last[0] + 1), indents, offsets):
                    self.input_tarea.delete(
                        start=(lno, indent),
                        end=(lno, indent + offset),
                        maintain_selection_offset=True,
                    )
            # add comment tokens to all lines
            else:
                indent = min([indent for indent, line in zip(indents, stripped_lines) if line])
                for lno, stripped_line in enumerate(stripped_lines, start=first[0]):
                    if stripped_line:
                        self.input_tarea.insert(
                            f"{inline_comment_marker} ",
                            location=(lno, indent),
                            maintain_selection_offset=True,
                        )

    def action_editor_keys(self) -> None:
        self.app.push_screen(TextEditorBindingsInfo())

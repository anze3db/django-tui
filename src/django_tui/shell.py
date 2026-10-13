from __future__ import annotations

import ast
import importlib
import os
import traceback
import warnings
from contextlib import redirect_stderr, redirect_stdout
from functools import lru_cache
from io import StringIO

from django.apps import apps
from rich.syntax import Syntax
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Label, MarkdownViewer, TextArea
from textual.widgets.text_area import Location

from django_tui.clipboard import copy_to_clipboard
from django_tui.header import AppHeader

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
            warnings.warn(f"django_admin_shell - autoimport warning :: {e}", ImportWarning, stacklevel=1)
            continue

        mods[module_name] = []
        for symbol_name in symbols:
            if hasattr(module, symbol_name):
                mods[module_name].append(symbol_name)
            else:
                warnings.warn(
                    "django_admin_shell - autoimport warning :: "
                    f"AttributeError module '{module_name}' has no attribute '{symbol_name}'",
                    ImportWarning,
                    stacklevel=1,
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


def run_code(code: str, namespace: dict) -> tuple[str, bool]:
    """
    Execute code in the namespace and return its output and whether it succeeded.
    Like the Python REPL, the value of a trailing expression is included in the output.
    """
    out = StringIO()
    with redirect_stdout(out), redirect_stderr(out):
        try:
            tree = ast.parse(code, "<shell>")
            last = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
            exec(compile(tree, "<shell>", "exec"), namespace)  # noqa: S102 (running code is the shell's job)
            if last is not None:
                value = eval(compile(ast.Expression(last.value), "<shell>", "eval"), namespace)
                if value is not None:
                    print(repr(value))
        except SyntaxError as e:
            out.write("".join(traceback.format_exception_only(e)))
            return out.getvalue(), False
        except Exception as e:
            # Hide django-tui's own frames, the traceback should start at the user's code
            tb = e.__traceback__
            while tb is not None and tb.tb_frame.f_code.co_filename != "<shell>":
                tb = tb.tb_next
            traceback.print_exception(type(e), e, tb, file=out)
            return out.getvalue(), False
    return out.getvalue(), True


class CodeEditor(TextArea):
    """A TextArea that closes brackets and quotes."""

    PAIRS = {"(": ")", "{": "}", "[": "]", "'": "'", '"': '"'}

    def _on_key(self, event: events.Key) -> None:
        if event.character in self.PAIRS.values() and self._next_character() == event.character:
            # Type over the closing character that was inserted automatically
            self.move_cursor_relative(columns=1)
            event.prevent_default()
        elif event.character in self.PAIRS:
            self.insert(f"{event.character}{self.PAIRS[event.character]}")
            self.move_cursor_relative(columns=-1)
            event.prevent_default()

    def _next_character(self) -> str:
        row, column = self.cursor_location
        return self.document.get_line(row)[column : column + 1]


class TextEditorBindingsInfo(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "dismiss(None)", "Close"),
    ]

    key_bindings = """
## Editor key bindings

| Key(s)           | Description                                          |
|------------------|------------------------------------------------------|
| ctrl+r           | Run the selection, or all code if nothing is selected. |
| ctrl+/           | Comment or uncomment the selected lines.             |
| escape           | Focus on the next item.                              |
| ctrl+left        | Move the cursor to the start of the word.            |
| ctrl+shift+left  | Move the cursor to the start of the word and select. |
| ctrl+right       | Move the cursor to the end of the word.              |
| ctrl+shift+right | Move the cursor to the end of the word and select.   |
| home,ctrl+a      | Move the cursor to the start of the line.            |
| end,ctrl+e       | Move the cursor to the end of the line.              |
| shift+home       | Move the cursor to the start of the line and select. |
| shift+end        | Move the cursor to the end of the line and select.   |
| pageup           | Move the cursor one page up.                         |
| pagedown         | Move the cursor one page down.                       |
| shift+arrows     | Select while moving the cursor.                      |
| ctrl+w           | Delete from cursor to start of the word.             |
| ctrl+f           | Delete from cursor to end of the word.               |
| ctrl+x           | Cut the selection or the current line.               |
| ctrl+c           | Copy the selection.                                  |
| ctrl+v           | Paste.                                               |
| ctrl+z, ctrl+y   | Undo, redo.                                          |
| ctrl+u           | Delete from cursor to the start of the line.         |
| ctrl+k           | Delete from cursor to the end of the line.           |
| f6               | Select the current line.                             |
| f7               | Select all text in the document.                     |
"""

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog") as dialog:
            dialog.border_subtitle = "esc to close"
            yield MarkdownViewer(self.key_bindings, show_table_of_contents=False)


class DefaultImportsInfo(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "dismiss(None)", "Close"),
    ]

    def __init__(self, imported_modules: str) -> None:
        super().__init__()
        self.imported_modules = imported_modules

    def compose(self) -> ComposeResult:
        syntax = Syntax(
            code=self.imported_modules,
            lexer="python",
            line_numbers=True,
            word_wrap=False,
            indent_guides=True,
            theme="dracula",
        )
        with VerticalScroll(classes="dialog") as dialog:
            dialog.border_title = "Imported automatically"
            dialog.border_subtitle = "esc to close"
            yield Label(syntax)


class ShellScreen(Screen):
    BINDINGS = [
        Binding("ctrl+r", "run_code", "Run", priority=True),
        Binding("f2", "default_imports", "Imports"),
        Binding("f3", "copy", "Copy output"),
        Binding("f1", "editor_keys", "Editor keys"),
        Binding("ctrl+underscore", "toggle_comment", "Toggle comment", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.namespace: dict = {}

    def compose(self) -> ComposeResult:
        yield AppHeader(mode="shell")
        with Horizontal(id="shell-body"):
            code = CodeEditor.code_editor(
                id="code",
                language="python",
                theme="css",
                placeholder="User.objects.filter(is_staff=True).count()",
            )
            code.border_title = "Code"
            code.border_subtitle = "ctrl+r to run"
            yield code
            output = TextArea(id="output", read_only=True, soft_wrap=True)
            output.border_title = "Output"
            yield output
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#code").focus()

    def action_default_imports(self) -> None:
        self.app.push_screen(DefaultImportsInfo(import_str()))

    def action_editor_keys(self) -> None:
        self.app.push_screen(TextEditorBindingsInfo())

    def action_run_code(self) -> None:
        editor = self.query_one("#code", CodeEditor)
        code = editor.selected_text or editor.text
        if not code.strip():
            return
        if not self.namespace:
            # The ORM refuses to run in the event loop's thread without this
            os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
            self.namespace = {"__name__": "__main__", **get_scope()}
        result, ok = run_code(code, self.namespace)
        output = self.query_one("#output", TextArea)
        output.load_text(result or "(no output)")
        output.set_class(not ok, "-error")

    def action_copy(self) -> None:
        output = self.query_one("#output", TextArea)
        text = output.selected_text or output.text
        if text:
            copy_to_clipboard(self.app, text)
            self.notify("Output copied to clipboard.")
        else:
            self.notify("Nothing to copy yet.", severity="warning")

    def _get_selected_lines(self) -> tuple[list[str], Location, Location]:
        editor = self.query_one("#code", CodeEditor)
        [first, last] = sorted([editor.selection.start, editor.selection.end])
        lines = [editor.document.get_line(i) for i in range(first[0], last[0] + 1)]
        return lines, first, last

    def action_toggle_comment(self) -> None:
        inline_comment_marker = "#"
        editor = self.query_one("#code", CodeEditor)

        lines, first, last = self._get_selected_lines()
        stripped_lines = [line.lstrip() for line in lines]
        indents = [len(line) - len(line.lstrip()) for line in lines]
        # if lines are already commented, remove them
        if lines and all(not line or line.startswith(inline_comment_marker) for line in stripped_lines):
            offsets = [
                0 if not line else (2 if line[len(inline_comment_marker) :][:1].isspace() else 1)
                for line in stripped_lines
            ]
            for lno, indent, offset in zip(range(first[0], last[0] + 1), indents, offsets):
                editor.delete(
                    start=(lno, indent),
                    end=(lno, indent + offset),
                    maintain_selection_offset=True,
                )
        # add comment tokens to all lines
        else:
            indent = min([indent for indent, line in zip(indents, stripped_lines) if line], default=0)
            for lno, stripped_line in enumerate(stripped_lines, start=first[0]):
                if stripped_line:
                    editor.insert(
                        f"{inline_comment_marker} ",
                        location=(lno, indent),
                        maintain_selection_offset=True,
                    )

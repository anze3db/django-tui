from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path
from subprocess import run
from typing import Any
from webbrowser import open as open_url

import click
from django.core.management import BaseCommand, get_commands, load_command_class
from rich.console import Console
from rich.highlighter import ReprHighlighter
from rich.text import Text
from textual import events, on
from textual.app import App, AutopilotCallbackType, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll, HorizontalScroll
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Label,
    Static,
    Tree,
    Header,
)
from textual.widgets.tree import TreeNode
from trogon.introspect import ArgumentSchema, CommandSchema, MultiValueParamData, OptionSchema
from trogon.run_command import UserCommandData
from trogon.widgets.about import TextDialog
from trogon.widgets.command_info import CommandInfo
from trogon.widgets.command_tree import CommandTree
from trogon.widgets.form import CommandForm
from trogon.widgets.multiple_choice import NonFocusableVerticalScroll
from textual.widgets import TextArea,Static
import django
import traceback
import importlib
import warnings
from django.apps import apps


from pprint import PrettyPrinter
from textual.widgets.text_area import Selection
from textual.widgets import Markdown
from textual.screen import ModalScreen
from textual.containers import Center
from textual.widgets._button import ButtonVariant
from textual.widgets import MarkdownViewer

try:
    # Only for python 2
    from StringIO import StringIO
except ImportError:
    # For python 3
    from io import StringIO



def get_py_version():
    ver = sys.version_info
    return "{0}.{1}.{2}".format(ver.major, ver.minor, ver.micro)

def get_dj_version():
    return django.__version__


DEFAULT_IMPORT = {
    'django.db.models': [
        'Avg',
        'Case',
        'Count',
        'F',
        'Max',
        'Min',
        'Prefetch',
        'Q',
        'Sum',
        'When',
    ],
    'django.conf': [
        'settings',
    ],
    'django.core.cache': [
        'cache',
    ],
    'django.contrib.auth': [
        'get_user_model',
    ],
    'django.utils': [
        'timezone',
    ],
    'django.urls': [
        'reverse'
    ],
}

class Importer(object):

    def __init__(self, import_django=None, import_models=None, extra_imports=None):
        self.import_django = import_django or True
        self.import_models = import_models or True
        self.FROM_DJANGO = DEFAULT_IMPORT
        if extra_imports is not None and isinstance(extra_imports, dict):
            self.FROM_DJANGO.update(extra_imports)

    _mods = None

    def get_modules(self):
        """
        Return list of modules and symbols to import
        """
        if self._mods is None:
            self._mods = {}

            if self.import_django and self.FROM_DJANGO:

                for module_name, symbols in self.FROM_DJANGO.items():
                    try:
                        module = importlib.import_module(module_name)
                    except ImportError as e:
                        warnings.warn(
                            "django_admin_shell - autoimport warning :: {msg}".format(
                                msg=str(e)
                            ),
                            ImportWarning
                        )
                        continue

                    self._mods[module_name] = []
                    for symbol_name in symbols:
                        if hasattr(module, symbol_name):
                            self._mods[module_name].append(symbol_name)
                        else:
                            warnings.warn(
                                "django_admin_shell - autoimport warning :: "
                                "AttributeError module '{mod}' has no attribute '{attr}'".format(
                                    mod=module_name,
                                    attr=symbol_name
                                ),
                                ImportWarning
                            )

            if self.import_models:
                for model_class in apps.get_models():
                    _mod = model_class.__module__
                    classes = self._mods.get(_mod, [])
                    classes.append(model_class.__name__)
                    self._mods[_mod] = classes

        return self._mods

    _scope = None

    def get_scope(self):
        """
        Return map with symbols to module/object
        Like:
        "reverse" -> "django.urls.reverse"
        """
        if self._scope is None:
            self._scope = {}
            for module_name, symbols in self.get_modules().items():
                module = importlib.import_module(module_name)
                for symbol_name in symbols:
                    self._scope[symbol_name] = getattr(
                        module,
                        symbol_name
                    )

        return self._scope

    def clear_scope(self):
        """
        clear the scope.

        Freeing declared variables to be garbage collected.
        """
        self._scope = None

    def __str__(self):
        buf = ""
        for module, symbols in self.get_modules().items():
            if symbols:
                buf += "from {mod} import {symbols}\n".format(
                    mod=module,
                    symbols=", ".join(symbols)
                )
        return buf

class Runner(object):

    def __init__(self):
        self.importer = Importer()

    def run_code(self, code):
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
            exec(code, None, self.importer.get_scope())
            # exec(code, globals())
        except Exception:
            out = traceback.format_exc()
            status = 'error'
        else:
            out = buf.getvalue()
        finally:
            sys.stdout = tmp_stdout

        result = {
            'code': code,
            'out':  out,
            'status': status,
        }
        return result


class ExtendedTextArea(TextArea):
    """A subclass of TextArea with parenthesis-closing functionality."""

    def _on_key(self, event: events.Key) -> None:
        if event.character == "(":
            self.insert("()")
            self.move_cursor_relative(columns=-1)
            event.prevent_default()


class TextEditorBingingsInfo(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "dismiss(None)", "", show=False),
    ]

    DEFAULT_CSS = """
    MarkdownViewer {
        align: center middle;
    }

    MarkdownViewer Center {
        width: 80%;
    }

    MarkdownViewer > Vertical {
        background: $boost;
        min-width: 30%;
        border: round blue;
    }

"""

    key_bindings = """
Text Editor Key Bindings List
| Key(s)      | Description                                 |
|-------------|---------------------------------------------|
| escape      | Focus on the next item.                     |
| up          | Move the cursor up.                         |
| down        | Move the cursor down.                       |
| left        | Move the cursor left.                       |
| ctrl+left   | Move the cursor to the start of the word.   |
| ctrl+shift+left | Move the cursor to the start of the word and select. |
| right       | Move the cursor right.                      |
| ctrl+right  | Move the cursor to the end of the word.      |
| ctrl+shift+right | Move the cursor to the end of the word and select. |
| home,ctrl+a | Move the cursor to the start of the line.    |
| end,ctrl+e  | Move the cursor to the end of the line.      |
| shift+home  | Move the cursor to the start of the line and select. |
| shift+end   | Move the cursor to the end of the line and select. |
| pageup      | Move the cursor one page up.                 |
| pagedown    | Move the cursor one page down.               |
| shift+up    | Select while moving the cursor up.           |
| shift+down  | Select while moving the cursor down.         |
| shift+left  | Select while moving the cursor left.         |
| shift+right | Select while moving the cursor right.        |
| backspace   | Delete character to the left of cursor.      |
| ctrl+w      | Delete from cursor to start of the word.     |
| delete,ctrl+d | Delete character to the right of cursor.    |
| ctrl+f      | Delete from cursor to end of the word.       |
| ctrl+x      | Delete the current line.                     |
| ctrl+u      | Delete from cursor to the start of the line. |
| ctrl+k      | Delete from cursor to the end of the line.   |
| f6          | Select the current line.                     |
| f7          | Select all text in the document.             |
"""
    _title = "Editor Keys Bindings"

    def compose(self) -> ComposeResult:
        """Compose the content of the modal dialog."""
        with Vertical():
            yield MarkdownViewer(self.key_bindings,classes="spaced",show_table_of_contents=False)
class AboutDialog(TextDialog):

    DEFAULT_CSS = """
    TextDialog > Vertical {
        border: thick $primary 50%;
    }
    """

    def __init__(self) -> None:
        title = "About"
        message = "Test"
        super().__init__(title, message)

class ShellApp(App):
    CSS_PATH = "ish.tcss"

    input_tarea = ExtendedTextArea("", language="python", theme="dracula")
    output_tarea =  TextArea("# Output", language="python", theme="dracula",classes="text-area")

    runner = Runner()

    BINDINGS = [
        Binding(key="ctrl+r", action="test", description="Run the query"),
        Binding(key="ctrl+z", action="copy_command", description="Copy to Clipboard"),
        Binding(key="f1", action="editor_keys", description="Key Bindings"),
        Binding(key="q", action="quit", description="Quit"),
    ]

    def compose(self) -> ComposeResult:
        self.input_tarea.focus()
        yield HorizontalScroll(
            self.input_tarea,
            self.output_tarea,
        )
        yield Label(f"Python: {get_py_version()}  Django: {get_dj_version()}")
        yield Footer()
    
    def action_test(self) -> None:
        # get Code from start till the position of the cursor
        self.input_tarea.selection = Selection(start=(0, 0), end=self.input_tarea.cursor_location)
        code = self.input_tarea.get_text_range(start=(0,0),end=self.input_tarea.cursor_location)

        

        if len(code) > 0:
            # Because the cli - texualize is running on a loop - has an event loop
            os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rest.settings')
            os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
            django.setup()

            result = self.runner.run_code(code)
            
            printer = PrettyPrinter()
            formatted = printer.pformat(result["out"])

            self.output_tarea.load_text(formatted)
            
    def action_copy_command(self) -> None:
        if sys.platform == "win32":
            copy_command = ["clip"]
        elif sys.platform == "darwin":
            copy_command = ["pbcopy"]
        else:
            copy_command = ["xclip", "-selection", "clipboard"]

        try:
            text_to_copy = self.input_tarea.selected_text 

            # self.notify(f"`{copy_command}`")
            # command = 'echo ' + text.strip() + '| clip'
            # os.system(command)

            run(
                copy_command,
                input=text_to_copy,
                text=True,
                check=False,
            )
            self.notify("Selction copied to clipboard.")
        except FileNotFoundError:
            self.notify(f"Could not copy to clipboard. `{copy_command[0]}` not found.", severity="error")

    def action_editor_keys(self) -> None:
        # self.notify(f"Selction:{self.input_tarea.BINDINGS}")
        self.app.push_screen(TextEditorBingingsInfo())

class Command(BaseCommand):
    help = """Run and inspect Django commands in a text-based user interface (TUI)."""

    def handle(self, *args: Any, **options: Any) -> None:
        app = ShellApp()
        app.run()

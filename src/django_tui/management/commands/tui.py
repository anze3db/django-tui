from __future__ import annotations

from typing import Any

from django.core.management import BaseCommand

from django_tui.app import DjangoTui
from django_tui.introspect import load_commands
from django_tui.runner import exec_command


class Command(BaseCommand):
    help = """Run and inspect Django commands in a text-based user interface (TUI)."""

    def add_arguments(self, parser):
        parser.add_argument("--shell", action="store_true", help="Open the interactive shell")

    def handle(self, *args: Any, shell=False, **options: Any) -> None:
        # Load the commands before Textual takes over the terminal. Importing them can have side effects on the
        # terminal, e.g. `import readline` resets the terminal mode on macOS.
        load_commands()
        # Commands normally run inside the TUI. It exits with a command when it has to run in a new process.
        command = DjangoTui(open_shell=shell).run()
        if command:
            exec_command(command)

from __future__ import annotations

import time
from pathlib import Path
from webbrowser import open as open_url

from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Static

from django_tui.clipboard import copy_to_clipboard
from django_tui.commands import CommandsScreen
from django_tui.runner import needs_new_process, program_name, run_and_wait
from django_tui.shell import ShellScreen

DJANGO_THEME = Theme(
    name="django",
    primary="#44B78B",
    secondary="#0C4B33",
    accent="#FFC757",
    success="#44B78B",
    warning="#FFC757",
    error="#E5534B",
    foreground="#E6EDE9",
    background="#0D1512",
    surface="#132019",
    panel="#1A2B23",
    dark=True,
)


class AboutDialog(ModalScreen[None]):
    BINDINGS = [Binding("escape,enter", "dismiss(None)", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog") as dialog:
            dialog.border_title = "About django-tui"
            dialog.border_subtitle = "esc to close"
            yield Static(
                "Built with [@click=app.visit('https://github.com/textualize/textual')]Textual[/] "
                "by [@click=app.visit('https://pecar.me')]Anže Pečar[/].\n\n"
                "Interactive Shell contributed by "
                "[@click=app.visit('https://github.com/shtayeb')]Shahryar Tayeb[/].\n\n"
                "[@click=app.visit('https://github.com/anze3db/django-tui')]https://github.com/anze3db/django-tui[/]"
            )


class DjangoTui(App[list[str]]):
    CSS_PATH = Path(__file__).parent / "tui.tcss"
    TITLE = "django-tui"
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (100, "-wide")]

    BINDINGS = [
        Binding("ctrl+j", "toggle_mode", "Shell / Commands", priority=True),
        Binding("ctrl+c", "copy_or_quit", "Quit", show=False, priority=True),
    ]

    QUIT_TIMEOUT = 2.0
    """Seconds to press ctrl+c again to quit."""

    def __init__(self, *, open_shell: bool = False) -> None:
        super().__init__()
        self.program = program_name()
        self.open_shell = open_shell
        self._quit_pressed_at = 0.0
        self.register_theme(DJANGO_THEME)
        self.theme = DJANGO_THEME.name

    def on_mount(self) -> None:
        self.add_mode("commands", lambda: CommandsScreen(self.program))
        self.add_mode("shell", ShellScreen)
        self.switch_mode("shell" if self.open_shell else "commands")

    def action_toggle_mode(self) -> None:
        self.switch_mode("commands" if self.current_mode == "shell" else "shell")

    def action_copy_or_quit(self) -> None:
        """Copy the selected text. Without a selection, press ctrl+c twice to quit."""
        selected = getattr(self.focused, "selected_text", "") or self.screen.get_selected_text()
        if selected:
            copy_to_clipboard(self, selected)
            return
        now = time.monotonic()
        if now - self._quit_pressed_at < self.QUIT_TIMEOUT:
            self.exit()
            return
        self._quit_pressed_at = now
        self.notify("Press [b]ctrl+c[/] again to quit.", timeout=self.QUIT_TIMEOUT)

    def action_about(self) -> None:
        self.push_screen(AboutDialog())

    def action_visit(self, url: str) -> None:
        open_url(url)

    def run_django_command(self, args: list[str]) -> None:
        """Run a command in this process and come back to the TUI afterwards.

        Falls back to exiting the TUI and starting the command in a new process when that's not possible.
        """
        if needs_new_process(args):
            self.exit(args)
            return
        try:
            with self.suspend():
                status = run_and_wait(args)
        except SuspendNotSupported:
            self.exit(args)
            return
        if status == 0:
            self.notify(f"{args[0]} finished.")
        else:
            self.notify(f"{args[0]} exited with status {status}.", severity="error")

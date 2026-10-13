from __future__ import annotations

import platform

import django
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

MODES = {"commands": "Commands", "shell": "Shell"}


class ModeTab(Static):
    def __init__(self, mode: str, *, active: bool) -> None:
        super().__init__(MODES[mode], classes="mode-tab -active" if active else "mode-tab")
        self.mode = mode

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.app.switch_mode(self.mode)


class AboutLink(Static):
    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.app.action_about()


class AppHeader(Horizontal):
    def __init__(self, mode: str) -> None:
        super().__init__()
        self.mode = mode

    def compose(self) -> ComposeResult:
        yield Static("django-tui", id="app-title")
        for mode in MODES:
            yield ModeTab(mode, active=mode == self.mode)
        yield Static(f"Django {django.get_version()} · Python {platform.python_version()}", id="versions")
        yield AboutLink("About", id="about-link")

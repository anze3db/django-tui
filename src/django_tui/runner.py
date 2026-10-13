"""Run management commands in the TUI's process, so Django doesn't have to start up again for every command."""

from __future__ import annotations

import asyncio
import os
import shlex
import signal
import sys
import threading
import traceback
from contextlib import contextmanager
from pathlib import Path

from django.core.management import ManagementUtility
from rich.console import Console

# These options configure Django before it starts, so they only work in a new process
NEW_PROCESS_OPTIONS = ("--settings", "--pythonpath")


def program() -> tuple[str, list[str]]:
    """Return how the user started the TUI (e.g. `python manage.py`) and the arguments to start it again."""
    script = sys.argv[0]
    if Path(script).name == "__main__.py":
        return "python -m django", [sys.executable, "-m", "django"]
    if script.endswith(".py"):
        return f"python {Path(script).name}", [sys.executable, script]
    return Path(script).name, [script]


def program_name() -> str:
    return program()[0]


def needs_new_process(args: list[str]) -> bool:
    return any(arg.split("=")[0] in NEW_PROCESS_OPTIONS for arg in args)


@contextmanager
def _outside_event_loop():
    """Hide the TUI's event loop from the command. The command runs in the loop's thread (while the TUI is
    suspended), which would make Django's ORM raise SynchronousOnlyOperation and asyncio.run() fail."""
    loop = asyncio._get_running_loop()
    asyncio._set_running_loop(None)
    try:
        yield
    finally:
        asyncio._set_running_loop(loop)


@contextmanager
def _default_sigint():
    """Make ctrl+c raise KeyboardInterrupt. While the TUI runs, asyncio handles it by cancelling the TUI instead."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    original = signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, original)


@contextmanager
def _argv(argv: list[str]):
    """runserver's autoreloader restarts the process with sys.argv, which should be the command, not the TUI."""
    original, sys.argv = sys.argv, argv
    try:
        yield
    finally:
        sys.argv = original


def run_in_process(args: list[str]) -> int:
    """Run a command like `manage.py` would and return its exit status."""
    argv = [sys.argv[0], *args]
    try:
        with _argv(argv), _outside_event_loop(), _default_sigint():
            ManagementUtility(argv).fetch_command(args[0]).run_from_argv(argv)
    except SystemExit as e:
        if e.code is None or isinstance(e.code, int):
            return e.code or 0
        print(e.code, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception:
        traceback.print_exc()
        return 1
    return 0


def run_and_wait(args: list[str]) -> int:
    """Run a command in the terminal and wait for the user before going back to the TUI."""
    console = Console()
    console.print(f"\n[b green]$[/] [dim]{program_name()}[/] [b]{shlex.join(args)}[/]\n")
    status = run_in_process(args)
    if status == 0:
        console.print("\n[b green]✔ Done.[/]", end=" ")
    else:
        console.print(f"\n[b red]✘ Exited with status {status}.[/]", end=" ")
    with _default_sigint():
        try:
            input("Press Enter to go back to django-tui.")
        except (EOFError, KeyboardInterrupt):
            pass
    return status


def exec_command(args: list[str]) -> None:
    """Replace the TUI process with the command."""
    name, argv = program()
    Console().print(f"Running [b cyan]{name} {shlex.join(args)}[/]")
    os.execvp(argv[0], [*argv, *args])

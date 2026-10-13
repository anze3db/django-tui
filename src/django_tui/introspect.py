from __future__ import annotations

import argparse
import os
import pickle
import select
import shlex
import signal
import time
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

from django.core.management import get_commands, load_command_class
from django.db import connections

# How long to wait for the child process that loads the commands before loading them in this process instead
LOAD_TIMEOUT = 30

# Options that every Django command accepts. They are shown separately so that a command's own options stand out.
COMMON_OPTIONS = {"verbosity", "settings", "pythonpath", "traceback", "no_color", "force_color", "skip_checks"}


class Kind(Enum):
    FLAG = "flag"
    """Passed without a value, e.g. `--noinput`."""
    CHOICE = "choice"
    """One value from a fixed list."""
    TEXT = "text"
    """A single value."""
    LIST = "list"
    """Any number of space separated values."""


@dataclass(frozen=True)
class Parameter:
    key: str
    """Unique within a command. Can't use `dest` because several options can share one (e.g. showmigrations)."""
    kind: Kind
    flags: tuple[str, ...] = ()
    """Option strings, e.g. `("-v", "--verbosity")`. Empty for positional arguments."""
    metavar: str = ""
    help: str = ""
    default: str = ""
    choices: tuple[str, ...] = ()
    required: bool = False
    repeat_flag: bool = False
    """Repeat the flag for every value, e.g. `--tag a --tag b` instead of `--tag a b`."""

    @property
    def is_positional(self) -> bool:
        return not self.flags

    @property
    def flag(self) -> str:
        """The flag to use on the command line. Prefers the first long flag since it is usually the most descriptive."""
        return next((f for f in self.flags if f.startswith("--")), self.flags[0] if self.flags else "")

    @property
    def label(self) -> str:
        return self.flag or self.metavar

    def to_args(self, value: str | bool) -> list[str]:
        if self.kind is Kind.FLAG:
            return [self.flag] if value else []
        values = split_values(value) if self.kind is Kind.LIST else [value] if value else []
        if not values:
            return []
        if self.is_positional:
            return values
        if self.repeat_flag:
            return [arg for v in values for arg in (self.flag, v)]
        return [self.flag, *values]


@dataclass(frozen=True)
class Command:
    name: str
    app: str
    """Short name of the app that provides the command, e.g. `auth` or `django` for Django's core commands."""
    help: str
    arguments: tuple[Parameter, ...]
    options: tuple[Parameter, ...]
    common_options: tuple[Parameter, ...]

    @property
    def parameters(self) -> tuple[Parameter, ...]:
        return self.arguments + self.options + self.common_options

    def missing(self, values: Mapping[str, str | bool]) -> list[Parameter]:
        """Return the arguments that need a value before the command can be run."""
        missing = []
        for i, argument in enumerate(self.arguments):
            if values.get(argument.key):
                continue
            # Positional arguments are matched by position, so an optional argument can't be skipped
            # if a later one is filled in.
            if argument.required or any(values.get(later.key) for later in self.arguments[i + 1 :]):
                missing.append(argument)
        return missing

    def to_args(self, values: Mapping[str, str | bool]) -> list[str]:
        """Return the command line arguments, starting with the command name."""
        args = [self.name]
        for parameter in self.parameters:
            args.extend(parameter.to_args(values.get(parameter.key, "")))
        return args

    def parse(self, args: list[str]) -> tuple[dict[str, str | bool], list[str]]:
        """Return the values for the arguments (without the command name), and any errors. The opposite of `to_args`.

        Parsing happens while the user is still typing, so incomplete input like an option without a value is fine.
        """
        by_flag = {flag: parameter for parameter in self.parameters for flag in parameter.flags}
        given: dict[Parameter, list[str]] = {}
        flags: set[Parameter] = set()
        errors = []
        positional = 0
        args = list(args)
        while args:
            arg = args.pop(0)
            if not _is_option(arg):
                if positional >= len(self.arguments):
                    errors.append(f"Unexpected argument {arg}")
                    continue
                parameter = self.arguments[positional]
                given.setdefault(parameter, []).append(arg)
                if parameter.kind is not Kind.LIST:
                    positional += 1
                continue

            flag, has_value, value = arg.partition("=")
            parameter = by_flag.get(flag)
            if parameter is None and not has_value and not arg.startswith("--") and len(arg) > 2:
                # A short option with its value attached, e.g. -v2
                parameter = by_flag.get(arg[:2])
                flag, has_value, value = arg[:2], True, arg[2:]
            if parameter is None or (parameter.kind is Kind.FLAG and has_value):
                errors.append(f"Unknown option {arg}")
                continue
            if parameter.kind is Kind.FLAG:
                flags.add(parameter)
            elif has_value:
                given.setdefault(parameter, []).append(value)
            elif parameter.kind is Kind.LIST and not parameter.repeat_flag:
                while args and not _is_option(args[0]):
                    given.setdefault(parameter, []).append(args.pop(0))
            elif args:
                given.setdefault(parameter, []).append(args.pop(0))

        values: dict[str, str | bool] = {parameter.key: True for parameter in flags}
        for parameter, items in given.items():
            if parameter.kind is Kind.LIST:
                values[parameter.key] = shlex.join(items)
                continue
            values[parameter.key] = items[-1]
            if parameter.kind is Kind.CHOICE and items[-1] not in parameter.choices:
                errors.append(f"{items[-1]} is not a valid choice for {parameter.label}")
        return values, errors


def _is_option(arg: str) -> bool:
    if not arg.startswith("-") or arg == "-":
        return False
    try:
        float(arg)
    except ValueError:
        return True
    # Negative numbers are values
    return False


def split_values(value: str | bool) -> list[str]:
    if not isinstance(value, str):
        return []
    try:
        return shlex.split(value)
    except ValueError:
        # Unbalanced quotes while the user is still typing
        return value.split()


def _kind(action: argparse.Action) -> Kind:
    if action.nargs == 0:
        return Kind.FLAG
    is_list = action.nargs in ("*", "+") or isinstance(action, argparse._AppendAction)
    if isinstance(action.nargs, int) and action.nargs > 1:
        is_list = True
    if action.choices and not is_list:
        return Kind.CHOICE
    return Kind.LIST if is_list else Kind.TEXT


def _default(action: argparse.Action) -> str:
    default = action.default
    if action.nargs == 0 or default in (None, argparse.SUPPRESS, False, [], ()):
        return ""
    if isinstance(default, (list, tuple)):
        return " ".join(map(str, default))
    return str(default)


def _help(parser: argparse.ArgumentParser, action: argparse.Action) -> str:
    if not action.help:
        return ""
    try:
        # Expands placeholders like %(default)s
        return parser._get_formatter()._expand_help(action)
    except (KeyError, TypeError, ValueError):
        return action.help


def _parameter(parser: argparse.ArgumentParser, action: argparse.Action, index: int) -> Parameter:
    kind = _kind(action)
    try:
        choices = tuple(str(choice) for choice in action.choices or ())
    except TypeError:
        choices = ()
    metavar = action.metavar if isinstance(action.metavar, str) else action.dest
    return Parameter(
        key=f"p{index}",
        kind=kind,
        flags=tuple(action.option_strings),
        metavar=metavar,
        help=_help(parser, action),
        default=_default(action),
        choices=choices,
        # Older Pythons mark nargs="*" positionals as required even though they accept no values
        required=bool(action.required) and action.nargs not in ("*", "?"),
        repeat_flag=isinstance(action, argparse._AppendAction),
    )


def _app_name(app_module: str) -> str:
    return "django" if app_module == "django.core" else app_module.rpartition(".")[-1]


def _app_order(app_module: str) -> tuple[bool, bool, str]:
    """Project apps first, then Django's own commands, then contrib apps."""
    is_django = app_module.startswith("django.")
    return (is_django, app_module != "django.core", _app_name(app_module))


@lru_cache
def introspect_django_commands() -> tuple[Command, ...]:
    commands = []
    for name, app_module in get_commands().items():
        try:
            parser = load_command_class(app_module, name).create_parser("manage.py", name)
        except Exception:  # noqa: S112
            # Skip commands that fail to load instead of breaking the whole TUI
            continue

        arguments, options, common_options = [], [], []
        for index, action in enumerate(parser._actions):
            if isinstance(action, (argparse._HelpAction, argparse._VersionAction)) or action.help == argparse.SUPPRESS:
                continue
            parameter = _parameter(parser, action, index)
            if parameter.is_positional:
                arguments.append(parameter)
            elif action.dest in COMMON_OPTIONS:
                common_options.append(parameter)
            else:
                options.append(parameter)

        command = Command(
            name=name,
            app=_app_name(app_module),
            help=(parser.description or "").strip(),
            arguments=tuple(arguments),
            options=tuple(options),
            common_options=tuple(common_options),
        )
        commands.append((_app_order(app_module), name, command))
    return tuple(command for *_, command in sorted(commands))


@lru_cache
def load_commands() -> tuple[Command, ...]:
    """Return all commands without importing their modules into this process.

    Importing a command's module can have side effects that `manage.py` never triggers, because it only imports the
    command it runs. For example, django-debug-toolbar's debugsqlshell makes every query print its SQL, and importing
    readline breaks the terminal on macOS. Load the commands in a short-lived child process instead, where possible.
    """
    if hasattr(os, "fork"):
        commands = _introspect_in_child()
        if commands is not None:
            return commands
    return introspect_django_commands()


def _introspect_in_child() -> tuple[Command, ...] | None:
    # The child must not use the database connections it would inherit
    connections.close_all()
    read_fd, write_fd = os.pipe()
    with warnings.catch_warnings():
        # Python warns that forking a process with threads may deadlock the child. The timeout below handles that.
        warnings.simplefilter("ignore", DeprecationWarning)
        pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            with os.fdopen(write_fd, "wb") as pipe:
                pipe.write(pickle.dumps(introspect_django_commands()))
        finally:
            # Skip cleanup like atexit handlers, those belong to the parent process
            os._exit(0)

    os.close(write_fd)
    data = b""
    deadline = time.monotonic() + LOAD_TIMEOUT
    with os.fdopen(read_fd, "rb") as pipe:
        while time.monotonic() < deadline:
            if select.select([pipe], [], [], deadline - time.monotonic())[0]:
                chunk = os.read(pipe.fileno(), 65536)
                if not chunk:
                    break
                data += chunk
        else:
            os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)
    try:
        return pickle.loads(data)
    except Exception:
        return None

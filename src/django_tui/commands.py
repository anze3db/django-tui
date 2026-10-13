from __future__ import annotations

import re
import shlex
import time

from rich.highlighter import Highlighter
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.suggester import Suggester
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Collapsible, ContentSwitcher, Footer, Input, OptionList, Select, Static
from textual.widgets.option_list import Option

from django_tui.clipboard import copy_to_clipboard
from django_tui.header import AppHeader
from django_tui.introspect import Command, Kind, Parameter, load_commands, split_values

# Building a form is the slow part of moving through the command list, so we wait for the highlight to settle and
# skip commands that are only passed through while an arrow key is held down. The wait adapts to the key repeat rate.
MIN_FORM_DELAY = 0.03
MAX_FORM_DELAY = 0.25

EMPTY_TITLE = "Type a command, or pick one with ↑ ↓"

Values = dict[str, str | bool]
FIELD_CHANGES = (Input.Changed, Checkbox.Changed, Select.Changed)


def matching(commands: list[Command], query: str) -> list[Command]:
    return [c for c in commands if query in c.name.casefold() or query in c.app.casefold()]


def best_match(commands: list[Command], query: str) -> Command | None:
    """The exact match, or else the first command that starts with the query, or else the first that contains it."""
    matches = matching(commands, query)
    return min(matches, key=lambda c: (c.name != query, not c.name.startswith(query))) if matches else None


class ParameterField(Widget):
    """A label, an input and help text for a single argument or option."""

    def __init__(self, parameter: Parameter, value: str | bool = "") -> None:
        super().__init__(classes=f"-{parameter.kind.value}")
        self.parameter = parameter
        self.initial_value = value

    def compose(self) -> ComposeResult:
        parameter = self.parameter
        if parameter.kind is Kind.FLAG:
            yield Checkbox(parameter.label, value=bool(self.initial_value), compact=True, classes="name")
            yield Static(parameter.help, classes="body help", markup=False)
            return
        label = Text(parameter.label, style="bold")
        if parameter.required:
            label.append(" *", style="bold red")
        yield Static(label, classes="name")
        with Vertical(classes="body"):
            if parameter.kind is Kind.CHOICE:
                initial = {"value": self.initial_value} if self.initial_value in parameter.choices else {}
                yield Select(
                    [(choice, choice) for choice in parameter.choices],
                    prompt=f"{parameter.default} (default)" if parameter.default else "Select…",
                    compact=True,
                    **initial,
                )
            else:
                yield Input(str(self.initial_value or ""), placeholder=self._placeholder(), compact=True)
            if parameter.help:
                yield Static(parameter.help, classes="help", markup=False)

    def _placeholder(self) -> str:
        parameter = self.parameter
        if parameter.default:
            return f"{parameter.default} (default)"
        if parameter.kind is Kind.LIST:
            return "one or more values, separated by spaces" if parameter.required else "space separated values"
        return "required" if parameter.required else ""

    @property
    def value(self) -> str | bool:
        if self.parameter.kind is Kind.FLAG:
            return self.query_one(Checkbox).value
        if self.parameter.kind is Kind.CHOICE:
            select = self.query_one(Select)
            return "" if select.is_blank() else str(select.value)
        return self.query_one(Input).value.strip()

    @value.setter
    def value(self, value: str | bool) -> None:
        if value == self.value:
            return
        if self.parameter.kind is Kind.FLAG:
            self.query_one(Checkbox).value = bool(value)
        elif self.parameter.kind is Kind.CHOICE:
            select = self.query_one(Select)
            if value in self.parameter.choices:
                select.value = value
            else:
                select.clear()
        else:
            self.query_one(Input).value = str(value)

    def focus(self, scroll_visible: bool = True) -> ParameterField:
        self.query_one("Checkbox, Select, Input").focus(scroll_visible)
        return self


class CommandForm(VerticalScroll, can_focus=False):
    BINDINGS = [
        Binding("ctrl+r", "screen.run", "Run"),
    ]

    def __init__(self, command: Command, values: Values, id: str) -> None:
        super().__init__(id=id)
        self.command = command
        self.values = values

    def compose(self) -> ComposeResult:
        command = self.command
        if command.arguments:
            yield Static("Arguments", classes="section-title")
            for parameter in command.arguments:
                yield ParameterField(parameter, self.values.get(parameter.key, ""))
        if command.options:
            yield Static("Options", classes="section-title")
            for parameter in command.options:
                yield ParameterField(parameter, self.values.get(parameter.key, ""))
        if not command.arguments and not command.options:
            yield Static("This command has no arguments or options of its own.", classes="section-title empty")
        if command.common_options:
            # The fields are added when expanded, which keeps building the form fast
            yield Collapsible(title=self._common_options_title(), collapsed=True)

    def _common_options_title(self) -> str:
        title = "Options shared by all commands"
        args = [arg for p in self.command.common_options for arg in p.to_args(self.values.get(p.key, ""))]
        return f"{title} · {shlex.join(args)}" if args else title

    @on(Collapsible.Expanded)
    async def add_common_options(self, event: Collapsible.Expanded) -> None:
        contents = event.collapsible.query_one(Collapsible.Contents)
        if not contents.children:
            await contents.mount_all(
                ParameterField(parameter, self.values.get(parameter.key, ""))
                for parameter in self.command.common_options
            )

    def update_fields(self) -> None:
        """Show the current values, e.g. after they were typed on the command line."""
        for field in self.query(ParameterField):
            field.value = self.values.get(field.parameter.key, "")
        self.update_common_options_title()

    def update_common_options_title(self) -> None:
        if self.command.common_options:
            self.query_one(Collapsible).title = self._common_options_title()

    def focus(self, scroll_visible: bool = True) -> CommandForm:
        fields = self.query(ParameterField)
        if fields:
            fields.first().focus(scroll_visible)
        return self

    def focus_parameter(self, parameter: Parameter) -> None:
        for field in self.query(ParameterField):
            if field.parameter is parameter:
                field.focus()


class CommandList(OptionList, can_focus=False):
    """Commands grouped by app. Driven by the command line, which keeps focus while browsing."""

    def show(self, commands: list[Command], query: str) -> None:
        """Show the commands and highlight the best match for the query."""
        options: list[Option | None] = []
        app = None
        for command in commands:
            if command.app != app:
                app = command.app
                if options:
                    options.append(None)
                options.append(Option(Text(app, style="bold"), disabled=True))
            name = Text(command.name)
            if query:
                name.highlight_words([query], style="bold underline", case_sensitive=False)
            options.append(Option(name, id=command.name))
        self.set_options(options)

        best = best_match(commands, query) if query else None
        if best is not None:
            self.highlighted = self.get_option_index(best.name)


class CommandLineHighlighter(Highlighter):
    def highlight(self, text: Text) -> None:
        for i, match in enumerate(re.finditer(r"\S+", text.plain)):
            if i == 0:
                text.stylize("bold", match.start(), match.end())
            elif match.group().startswith("-"):
                text.stylize("cyan", match.start(), match.end())


class CommandSuggester(Suggester):
    """Completes the command name."""

    def __init__(self, commands: list[Command]) -> None:
        super().__init__(use_cache=False, case_sensitive=True)
        self.commands = commands

    async def get_suggestion(self, value: str) -> str | None:
        if not value or " " in value:
            return None
        best = best_match(self.commands, value.casefold())
        return best.name if best is not None and best.name.startswith(value) else None


class CommandLine(Input):
    """Type a command and its arguments. The command name filters the command list, the arguments fill in the form."""

    BINDINGS = [
        Binding("enter", "screen.run", "Run"),
        Binding("tab", "screen.edit_options", "Edit options"),
        Binding("down", "screen.move('cursor_down')", show=False),
        Binding("up", "screen.move('cursor_up')", show=False),
        Binding("pagedown", "screen.move('page_down')", show=False),
        Binding("pageup", "screen.move('page_up')", show=False),
    ]

    @property
    def command_name(self) -> str:
        return self.value.lstrip().partition(" ")[0]

    @property
    def args(self) -> list[str]:
        return split_values(self.value.lstrip().partition(" ")[2])


class CommandsScreen(Screen):
    BINDINGS = [
        Binding("ctrl+r", "run", "Run", show=False),
        Binding("ctrl+y", "copy", "Copy command"),
        Binding("escape", "focus_command_line", "Command line"),
    ]

    def __init__(self, program: str) -> None:
        super().__init__()
        self.program = program
        self.commands = [command for command in load_commands() if command.name != "tui"]
        self._commands_by_name = {command.name: command for command in self.commands}
        self._values: dict[str, Values] = {command.name: {} for command in self.commands}
        """The arguments and options for each command. Both the command line and the form edit these."""
        self._errors: list[str] = []
        self._query = ""
        self.command: Command | None = None
        self._form_timer: Timer | None = None
        self._form_delay = MIN_FORM_DELAY
        self._last_selected = 0.0

    def compose(self) -> ComposeResult:
        yield AppHeader(mode="commands")
        with Horizontal(id="command-bar"):
            yield Static(Text.assemble(("$ ", "bold green"), (self.program, "dim")), id="prompt")
            yield CommandLine(
                placeholder="Type a command, e.g. migrate",
                id="command-line",
                highlighter=CommandLineHighlighter(),
                suggester=CommandSuggester(self.commands),
                compact=True,
            )
            yield Button("Copy", id="copy", compact=True)
            yield Button("Run ▶", id="run", variant="success", compact=True)
        with Horizontal(id="body"):
            yield CommandList(id="command-list")
            with Vertical(id="main"):
                with Vertical(id="command-header"):
                    yield Static(EMPTY_TITLE, id="command-title")
                    yield Static(id="command-help")
                    yield Static(id="command-status")
                yield ContentSwitcher(id="forms")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(CommandList).show(self.commands, "")
        self.query_one(CommandLine).focus()

    @property
    def values(self) -> Values:
        return self._values[self.command.name] if self.command else {}

    # The command line

    @on(Input.Changed, "#command-line")
    def command_line_changed(self) -> None:
        command_line = self.query_one(CommandLine)
        query = command_line.command_name.casefold()
        if query != self._query:
            self._query = query
            self.query_one(CommandList).show(matching(self.commands, query), query)
        self.select_command(best_match(self.commands, query) if query else None)
        if self.command is None:
            return
        values, self._errors = self.command.parse(command_line.args)
        self.values.clear()
        self.values.update(values)
        form = self._find_form(self.command)
        if form is not None:
            with self.prevent(*FIELD_CHANGES):
                form.update_fields()
        self.update_status()

    def _set_command_line(self) -> None:
        """Show the current command and its values on the command line."""
        command_line = self.query_one(CommandLine)
        value = shlex.join(self.command.to_args(self.values)) if self.command else ""
        with self.prevent(Input.Changed):
            command_line.value = value
        command_line.cursor_position = len(value)

    def action_move(self, action: str) -> None:
        command_list = self.query_one(CommandList)
        getattr(command_list, f"action_{action}")()
        if command_list.highlighted_option is not None:
            self.select_command(self._commands_by_name[command_list.highlighted_option.id])
            self._errors = []
            self._set_command_line()
            self.update_status()

    @on(OptionList.OptionSelected)
    def command_clicked(self, event: OptionList.OptionSelected) -> None:
        self.select_command(self._commands_by_name[event.option.id])
        self._errors = []
        self._set_command_line()
        self.update_status()
        self.query_one(CommandLine).focus()

    @on(OptionList.OptionHighlighted)
    def command_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self.select_command(self._commands_by_name[event.option.id])

    def action_focus_command_line(self) -> None:
        command_line = self.query_one(CommandLine)
        if command_line.has_focus:
            command_line.clear()
        command_line.focus()

    # The form

    @on(Input.Changed, "ParameterField Input")
    @on(Checkbox.Changed, "ParameterField Checkbox")
    @on(Select.Changed, "ParameterField Select")
    def field_changed(self, event: Input.Changed | Checkbox.Changed | Select.Changed) -> None:
        field = next(node for node in event.control.ancestors if isinstance(node, ParameterField))
        self.values[field.parameter.key] = field.value
        next(node for node in field.ancestors if isinstance(node, CommandForm)).update_common_options_title()
        self._errors = []
        self._set_command_line()
        self.update_status()

    async def action_edit_options(self, parameter: Parameter | None = None) -> None:
        if self.command is None:
            return
        if self.query_one(CommandLine).command_name != self.command.name:
            # Complete the command name first
            self._set_command_line()
        await self._show_form(self.command)
        form = self._find_form(self.command)
        if parameter is None:
            form.focus()
        else:
            form.focus_parameter(parameter)

    def select_command(self, command: Command | None) -> None:
        if command is self.command:
            return
        self.command = command
        self._update_form_delay()
        if self._form_timer is not None:
            self._form_timer.stop()
        title = self.query_one("#command-title", Static)
        help_text = self.query_one("#command-help", Static)
        if command is None:
            title.update("No matching commands" if self._query else EMPTY_TITLE)
            help_text.update("")
            self.query_one(ContentSwitcher).current = None
        else:
            title.update(Text.assemble((command.name, "bold"), "  ", (command.app, "dim")))
            help_text.update(Text(command.help or "No description."))
            if self._find_form(command):
                self.query_one(ContentSwitcher).current = self._form_id(command)
            else:
                self.query_one(ContentSwitcher).current = None
                self._form_timer = self.set_timer(self._form_delay, lambda: self._show_form(command))
        self.update_status()

    def _update_form_delay(self) -> None:
        now = time.monotonic()
        since_last, self._last_selected = now - self._last_selected, now
        if since_last > MAX_FORM_DELAY:
            self._form_delay = MIN_FORM_DELAY
        else:
            # Moving quickly, probably holding down a key. Wait longer than the time between key repeats.
            self._form_delay = min(max(2 * since_last, MIN_FORM_DELAY), MAX_FORM_DELAY)

    @staticmethod
    def _form_id(command: Command) -> str:
        return "form-" + re.sub(r"[^\w-]", "_", command.name)

    def _find_form(self, command: Command) -> CommandForm | None:
        forms = self.query_one(ContentSwitcher).query_children(f"#{self._form_id(command)}")
        return forms.first(CommandForm) if forms else None

    async def _show_form(self, command: Command) -> None:
        if command is not self.command:
            return
        switcher = self.query_one(ContentSwitcher)
        if self._find_form(command) is None:
            await switcher.mount(CommandForm(command, self._values[command.name], id=self._form_id(command)))
        switcher.current = self._form_id(command)

    def update_status(self) -> None:
        status = self.query_one("#command-status", Static)
        missing = self.command.missing(self.values) if self.command else []
        if self._errors:
            status.update(Text("  ".join(self._errors), style="bold red"))
        elif missing:
            status.update(Text("Needs " + " ".join(f"<{p.label}>" for p in missing), style="bold yellow"))
        else:
            status.update("")
        status.display = bool(self._errors or missing)

    # Running

    async def _command_line(self) -> list[str] | None:
        """Return the arguments to run, or `None` after taking the user to the missing arguments."""
        if self.command is None:
            return None
        missing = self.command.missing(self.values)
        if missing:
            labels = ", ".join(parameter.label for parameter in missing)
            self.notify(f"Fill in {labels} first.", title="Missing arguments", severity="warning")
            await self.action_edit_options(missing[0])
            return None
        command_line = self.query_one(CommandLine)
        if command_line.command_name != self.command.name:
            self._set_command_line()
        # Run what's on the command line, Django reports anything it doesn't understand
        return [self.command.name, *command_line.args]

    @on(Button.Pressed, "#run")
    @on(Input.Submitted, "ParameterField Input")
    async def action_run(self) -> None:
        args = await self._command_line()
        if args is not None:
            self.app.run_django_command(args)

    @on(Button.Pressed, "#copy")
    async def action_copy(self) -> None:
        args = await self._command_line()
        if args is not None:
            command = " ".join([self.program, shlex.join(args)])
            copy_to_clipboard(self.app, command)
            self.notify(command, title="Copied to clipboard")

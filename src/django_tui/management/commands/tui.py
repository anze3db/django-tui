from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path
from subprocess import run
from typing import Any, Literal
from webbrowser import open as open_url

import click
from django.core.management import BaseCommand, get_commands, load_command_class
from rich.console import Console
from rich.highlighter import ReprHighlighter
from rich.text import Text
from textual import events, on
from textual.app import App, AutopilotCallbackType, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Label,
    Static,
    Tree,
)
from textual.widgets.tree import TreeNode
from trogon.introspect import ArgumentSchema, CommandSchema, MultiValueParamData, OptionSchema
from trogon.run_command import UserCommandData
from trogon.widgets.about import TextDialog
from trogon.widgets.command_info import CommandInfo
from trogon.widgets.command_tree import CommandTree
from trogon.widgets.form import CommandForm
from trogon.widgets.multiple_choice import NonFocusableVerticalScroll

from django_tui.management.commands.ish import InteractiveShellScreen


def introspect_django_commands() -> dict[str, CommandSchema]:
    groups = {}
    for name, app_name in get_commands().items():
        try:
            kls = load_command_class(app_name, name)
        except AttributeError:
            # Skip invalid commands
            continue
        if app_name == "django.core":
            group_name = "django"
        else:
            group_name = app_name.rpartition(".")[-1]

        parser = kls.create_parser(f"django {name}", name)
        options = []
        args = []
        root = []
        for action in parser._actions:
            if action.nargs == "?":
                nargs = 1
            elif action.nargs in ("*", "+"):
                nargs = -1
            elif not action.nargs:
                nargs = 1
            else:
                nargs = action.nargs

            if hasattr(action, "type"):
                if action.type is bool:
                    type_ = click.BOOL
                elif action.type is int:
                    type_ = click.INT
                elif action.type is str:
                    type_ = click.STRING
                else:
                    type_ = click.STRING if action.nargs != 0 else click.BOOL
            else:
                type_ = click.STRING if action.nargs != 0 else click.BOOL

            default = action.default
            if default is None:
                default = MultiValueParamData([])
            elif type_ is click.BOOL:
                default = MultiValueParamData([])
            else:
                default = MultiValueParamData(values=[(default,)])

            if not action.option_strings:
                args.append(
                    ArgumentSchema(
                        name=action.metavar or action.dest,
                        type=type_,
                        required=action.required if action.nargs != "*" else False,
                        default=default,
                        choices=action.choices,
                        multiple=action.nargs in ("+", "*"),
                        nargs=nargs,
                    )
                )
                continue
            option_name = action.option_strings[0]

            schema = OptionSchema(
                name=option_name,
                type=type_,
                help=action.help,
                default=default,
                required=action.required,
                multiple=action.nargs in ("+", "*"),
                choices=action.choices,
                is_flag=action.nargs == 0,
                is_boolean_flag=action.nargs == 0,
                nargs=nargs,
            )
            if option_name in (
                "-h",
                "--version",
                "-v",
                "--settings",
                "--pythonpath",
                "--traceback",
                "--no-color",
                "--force-color",
                "--skip-checks",
            ):
                root.append(schema)
            else:
                options.append(schema)

        if group_name not in groups:
            groups[group_name] = CommandSchema(name=group_name, function=None, is_group=True, options=root)

        command = CommandSchema(
            name=name,
            function=None,
            is_group=False,
            docstring=None,
            options=options,
            arguments=args,
            parent=groups[group_name],
        )

        groups[group_name].subcommands[name] = command

    return groups


class AboutDialog(TextDialog):
    DEFAULT_CSS = """
    TextDialog > Vertical {
        border: thick $primary 50%;
    }
    """

    def __init__(self) -> None:
        title = "About django-tui"
        message = Text.from_markup(
            "Built with [@click=app.visit('https://github.com/textualize/textual')]Textual[/] & [@click=app.visit('https://github.com/textualize/trogon')]Trogon[/] "
            "by [@click=app.visit('https://pecar.me')]Anže Pečar[/].\n\n"
            "Interactive Shell contributed by [@click=app.visit('https://github.com/shtayeb')]Shahryar Tayeb[/].\n\n"
            "[@click=app.visit('https://github.com/anze3db/django-tui')]"
            "https://github.com/anze3db/django-tui[/]",
        )
        super().__init__(title, message)


# 2 For the command screen
class DjangoCommandBuilder(Screen):
    COMPONENT_CLASSES = {"version-string", "prompt", "command-name-syntax"}

    def __init__(
        self,
        click_app_name: str,
        command_name: str,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        super().__init__(name, id, classes)
        self.command_data = None
        self.is_grouped_cli = True

        self.command_schemas = introspect_django_commands()
        self.click_app_name = click_app_name
        self.command_name = command_name

        try:
            self.version = metadata.version(self.click_app_name)
        except Exception:
            self.version = None

        self.highlighter = ReprHighlighter()

    def compose(self) -> ComposeResult:
        tree = CommandTree("Commands", self.command_schemas, self.command_name)

        title_parts = [Text(self.click_app_name, style="b")]
        if self.version:
            version_style = self.get_component_rich_style("version-string")
            title_parts.extend(["\n", (f"v{self.version}", version_style)])

        title = Text.assemble(*title_parts)

        sidebar = Vertical(
            Label(title, id="home-commands-label"),
            tree,
            id="home-sidebar",
        )
        if self.is_grouped_cli:
            # If the root of the click app is a Group instance, then
            #  we display the command tree to users and focus it.
            tree.focus()
        else:
            # If the click app is structured using a single command,
            #  there's no need for us to display the command tree.
            sidebar.display = False

        yield sidebar

        with Vertical(id="home-body"):
            with Horizontal(id="home-command-description-container") as vs:
                vs.can_focus = False
                yield Static(self.click_app_name or "", id="home-command-description")

            scrollable_body = VerticalScroll(
                Static(""),
                id="home-body-scroll",
            )
            scrollable_body.can_focus = False
            yield scrollable_body
            yield Horizontal(
                NonFocusableVerticalScroll(
                    Static("", id="home-exec-preview-static"),
                    id="home-exec-preview-container",
                ),
                # Vertical(
                #     Button.success("Close & Run", id="home-exec-button"),
                #     id="home-exec-preview-buttons",
                # ),
                id="home-exec-preview",
            )

        yield Footer()

    def action_close_and_run(self) -> None:
        self.app.execute_on_exit = True
        self.app.exit()

    async def on_mount(self, event: events.Mount) -> None:
        await self._refresh_command_form()

    async def _refresh_command_form(self, node: TreeNode[CommandSchema] | None = None):
        if node is None:
            try:
                command_tree = self.query_one(CommandTree)
                node = command_tree.cursor_node
            except NoMatches:
                return

        self.selected_command_schema = node.data
        self._update_command_description(node)
        self._update_execution_string_preview(self.selected_command_schema, self.command_data)
        await self._update_form_body(node)

    @on(Tree.NodeHighlighted)
    async def selected_command_changed(self, event: Tree.NodeHighlighted[CommandSchema]) -> None:
        """When we highlight a node in the CommandTree, the main body of the home page updates
        to display a form specific to the highlighted command."""
        await self._refresh_command_form(event.node)

    @on(CommandForm.Changed)
    def update_command_data(self, event: CommandForm.Changed) -> None:
        self.command_data = event.command_data
        self._update_execution_string_preview(self.selected_command_schema, self.command_data)

    def _update_command_description(self, node: TreeNode[CommandSchema]) -> None:
        """Update the description of the command at the bottom of the sidebar
        based on the currently selected node in the command tree."""
        description_box = self.query_one("#home-command-description", Static)
        description_text = getattr(node.data, "docstring", "") or ""
        description_text = description_text.lstrip()
        description_text = f"[b]{node.label if self.is_grouped_cli else self.click_app_name}[/]\n{description_text}"
        description_box.update(description_text)

    def _update_execution_string_preview(self, command_schema: CommandSchema, command_data: UserCommandData) -> None:
        """Update the preview box showing the command string to be executed"""
        if self.command_data is not None:
            command_name_syntax_style = self.get_component_rich_style("command-name-syntax")
            prefix = Text(f"{self.click_app_name} ", command_name_syntax_style)
            new_value = command_data.to_cli_string(include_root_command=False)
            highlighted_new_value = Text.assemble(prefix, self.highlighter(new_value))
            prompt_style = self.get_component_rich_style("prompt")
            preview_string = Text.assemble(("$ ", prompt_style), highlighted_new_value)
            self.query_one("#home-exec-preview-static", Static).update(preview_string)

    async def _update_form_body(self, node: TreeNode[CommandSchema]) -> None:
        # self.query_one(Pretty).update(node.data)
        parent = self.query_one("#home-body-scroll", VerticalScroll)
        for child in parent.children:
            await child.remove()

        # Process the metadata for this command and mount corresponding widgets
        command_schema = node.data
        command_form = CommandForm(command_schema=command_schema, command_schemas=self.command_schemas)
        await parent.mount(command_form)
        if not self.is_grouped_cli:
            command_form.focus()


class DjangoTui(App):
    CSS_PATH = Path(__file__).parent / "trogon.scss"

    BINDINGS = [
        Binding(key="ctrl+r", action="close_and_run", description="Close & Run"),
        Binding(key="ctrl+z", action="copy_command", description="Copy Command to Clipboard"),
        Binding(key="ctrl+t", action="focus_command_tree", description="Focus Command Tree"),
        # Binding(key="ctrl+o", action="show_command_info", description="Command Info"),
        Binding(key="ctrl+s", action="focus('search')", description="Search"),
        Binding(key="ctrl+j", action="select_mode('shell')", description="Shell"),
        Binding(key="f1", action="about", description="About"),
    ]

    def __init__(
        self,
        *,
        open_shell: bool = False,
    ) -> None:
        super().__init__()
        self.post_run_command: list[str] = []
        self.is_grouped_cli = True
        self.execute_on_exit = False
        self.app_name = "python manage.py"
        self.command_name = "django-tui"
        self.open_shell = open_shell

    def on_mount(self):
        if self.open_shell:
            self.push_screen(InteractiveShellScreen("Interactive Shell"))
        else:
            self.push_screen(DjangoCommandBuilder(self.app_name, self.command_name))
            # self.push_screen(HomeScreen(self.app_name))

    @on(Button.Pressed, "#home-exec-button")
    def on_button_pressed(self):
        self.execute_on_exit = True
        self.exit()

    def run(
        self,
        *,
        headless: bool = False,
        size: tuple[int, int] | None = None,
        auto_pilot: AutopilotCallbackType | None = None,
    ) -> None:
        try:
            super().run(headless=headless, size=size, auto_pilot=auto_pilot)
        finally:
            if self.post_run_command:
                console = Console()
                if self.post_run_command and self.execute_on_exit:
                    console.print(
                        f"Running [b cyan]{self.app_name} {' '.join(shlex.quote(s) for s in self.post_run_command)}[/]"
                    )

                    split_app_name = shlex.split(self.app_name)
                    program_name = shlex.split(self.app_name)[0]
                    arguments = [*split_app_name, *self.post_run_command]
                    os.execvp(program_name, arguments)

    @on(CommandForm.Changed)
    def update_command_to_run(self, event: CommandForm.Changed):
        include_root_command = not self.is_grouped_cli
        self.post_run_command = event.command_data.to_cli_args(include_root_command)

    def action_focus_command_tree(self) -> None:
        try:
            command_tree = self.query_one(CommandTree)
        except NoMatches:
            return

        command_tree.focus()

    def action_show_command_info(self) -> None:
        command_builder = self.query_one(DjangoCommandBuilder)
        self.push_screen(CommandInfo(command_builder.selected_command_schema))

    def action_visit(self, url: str) -> None:
        """Visit the given URL, via the operating system.

        Args:
            url: The URL to visit.
        """
        open_url(url)

    def action_select_mode(self, mode_id: Literal["commands", "shell"]) -> None:
        if mode_id == "commands":
            self.app.push_screen(DjangoCommandBuilder("pyhton manage.py", "Test command name"))

        elif mode_id == "shell":
            self.app.push_screen(InteractiveShellScreen("Interactive Shell"))

    def action_copy_command(self) -> None:
        command = self.app_name + " " + " ".join(shlex.quote(str(x)) for x in self.post_run_command)
        self.copy_to_clipboard(command)
        self.notify(f"`{command}` copied to clipboard.")

    def action_about(self) -> None:
        self.app.push_screen(AboutDialog())


class Command(BaseCommand):
    help = """Run and inspect Django commands in a text-based user interface (TUI)."""

    def add_arguments(self, parser):
        parser.add_argument("--shell", action="store_true", help="Open django shell")

    def handle(self, *args: Any, shell=False, **options: Any) -> None:
        app = DjangoTui(open_shell=shell)
        app.run()

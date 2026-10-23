import asyncio
import os
import sys
from contextlib import nullcontext

from textual.widgets import Checkbox, Collapsible, Input, TextArea

from django_tui import app as app_module
from django_tui.app import DjangoTui
from django_tui.commands import CommandForm, CommandLine, CommandList, CommandsScreen, ParameterField
from django_tui.introspect import Command, Kind, Parameter, introspect_django_commands, load_commands
from django_tui.runner import needs_new_process, run_in_process
from django_tui.shell import ShellScreen, get_scope, run_code


def get_command(name: str) -> Command:
    return next(command for command in introspect_django_commands() if command.name == name)


def by_label(command: Command, label: str) -> Parameter:
    return next(parameter for parameter in command.parameters if parameter.label == label)


def test_introspect_django_commands():
    commands = introspect_django_commands()
    names = [command.name for command in commands]

    assert "migrate" in names
    assert get_command("migrate").app == "django"
    assert get_command("changepassword").app == "auth"
    # Project and third party apps first, then Django's own commands
    assert [command.app for command in commands[:2]] == ["cmdapp", "django_tui"]


def test_load_commands_without_importing_them():
    sys.modules.pop("tests.cmdapp.management.commands.sideeffect", None)
    os.environ.pop("DJANGO_TUI_SIDE_EFFECT", None)
    load_commands.cache_clear()
    introspect_django_commands.cache_clear()

    assert "sideeffect" in [command.name for command in load_commands()]
    assert "DJANGO_TUI_SIDE_EFFECT" not in os.environ
    assert "tests.cmdapp.management.commands.sideeffect" not in sys.modules


def test_introspect_parameters():
    migrate = get_command("migrate")

    assert [p.label for p in migrate.arguments] == ["app_label", "migration_name"]
    assert by_label(migrate, "--plan").kind is Kind.FLAG
    assert by_label(migrate, "--database").kind is Kind.CHOICE
    assert by_label(migrate, "--database").default == "default"
    assert "--verbosity" in [p.label for p in migrate.common_options]
    assert "--verbosity" not in [p.label for p in migrate.options]
    assert not [p for p in migrate.parameters if p.label in ("-h", "--help", "--version")]


def test_parameters_sharing_a_dest_have_unique_keys():
    showmigrations = get_command("showmigrations")

    keys = [p.key for p in showmigrations.parameters]
    assert len(keys) == len(set(keys))
    assert {"--list", "--plan"} <= {p.label for p in showmigrations.options}


def test_to_args():
    check = get_command("check")
    values = {
        check.arguments[0].key: "auth contenttypes",
        by_label(check, "--tag").key: "models urls",
        by_label(check, "--deploy").key: True,
        by_label(check, "--fail-level").key: "WARNING",
        by_label(check, "--verbosity").key: "",
    }

    assert check.to_args(values) == [
        "check",
        "auth",
        "contenttypes",
        "--tag",
        "models",
        "--tag",
        "urls",
        "--deploy",
        "--fail-level",
        "WARNING",
    ]


def test_missing_arguments():
    sqlmigrate = get_command("sqlmigrate")
    app_label, migration_name = sqlmigrate.arguments

    assert sqlmigrate.missing({}) == [app_label, migration_name]
    assert sqlmigrate.missing({app_label.key: "auth", migration_name.key: "0001"}) == []

    migrate = get_command("migrate")
    app_label, migration_name = migrate.arguments
    assert migrate.missing({}) == []
    assert get_command("showmigrations").missing({}) == []
    # Positional arguments can't be skipped
    assert migrate.missing({migration_name.key: "0001"}) == [app_label]


def test_parse():
    migrate = get_command("migrate")
    app_label = migrate.arguments[0]

    values, errors = migrate.parse(["myapp", "--plan", "-v2", "--database=default"])
    assert errors == []
    assert values == {
        app_label.key: "myapp",
        by_label(migrate, "--plan").key: True,
        by_label(migrate, "--verbosity").key: "2",
        by_label(migrate, "--database").key: "default",
    }
    assert migrate.to_args(values) == ["migrate", "myapp", "--database", "default", "--plan", "--verbosity", "2"]

    # Incomplete input while typing isn't an error
    assert migrate.parse(["--database"]) == ({}, [])
    assert migrate.parse(["a", "b", "c", "--nope"])[1] == ["Unexpected argument c", "Unknown option --nope"]
    assert migrate.parse(["--database", "nope"])[1] == ["nope is not a valid choice for --database"]

    check = get_command("check")
    values, errors = check.parse(["auth", "admin", "--tag", "models", "--tag", "urls"])
    assert values == {check.arguments[0].key: "auth admin", by_label(check, "--tag").key: "models urls"}


def test_run_code():
    namespace = {**get_scope()}

    assert run_code("x = 41", namespace) == ("", True)
    assert run_code("def f():\n    return x + 1\nf()", namespace) == ("42\n", True)
    output, ok = run_code("1/0", namespace)
    assert not ok
    assert output.startswith('Traceback (most recent call last):\n  File "<shell>"')


def run_app(test, **kwargs):
    async def run():
        app = DjangoTui(**kwargs)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await test(app, pilot)
        return app.return_value

    return asyncio.run(run())


def test_enter_runs_with_defaults():
    async def test(app, pilot):
        await pilot.press(*"migr")
        assert app.screen.query_one(CommandList).highlighted_option.id == "migrate"
        await pilot.press("enter")

    # Headless apps can't suspend, so the TUI exits with the command to run it in a new process
    assert run_app(test) == ["migrate"]


def test_form_timer_firing_after_the_tui_closes():
    async def run():
        app = DjangoTui()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press(*"migr")
            screen = app.screen
            await pilot.press("enter")
        await screen._show_form(screen.command)
        return app.return_value

    assert asyncio.run(run()) == ["migrate"]


def test_enter_on_empty_command_line_does_nothing():
    async def test(app, pilot):
        await pilot.press("enter")
        assert app.is_running

    assert run_app(test) is None


def test_edit_options_and_run():
    async def test(app, pilot):
        await pilot.press(*"migr", "tab")
        # Tab completes the command name
        assert app.screen.query_one(CommandLine).value == "migrate"
        assert isinstance(app.focused, Input)
        assert app.focused.parent.parent.parameter.label == "app_label"

        await pilot.press(*"auth")
        assert app.screen.query_one(CommandLine).value == "migrate auth"
        await pilot.press("enter")

    assert run_app(test) == ["migrate", "auth"]


def test_command_line_fills_in_the_form():
    async def test(app, pilot):
        await pilot.press(*"migrate myapp --plan", "tab")
        form = app.screen.query_one("#forms").visible_content
        fields = {field.parameter.label: field for field in form.query(ParameterField)}
        assert fields["app_label"].value == "myapp"
        assert fields["--plan"].value is True

        # And the form updates the command line
        await pilot.click(fields["--plan"].query_one(Checkbox))
        await pilot.click(fields["--fake"].query_one(Checkbox))
        assert app.screen.query_one(CommandLine).value == "migrate myapp --fake"

        # Typing again updates the form that's already there
        app.screen.query_one(CommandLine).value = "migrate other"
        await pilot.pause()
        assert fields["app_label"].value == "other"
        assert fields["--fake"].value is False

    run_app(test)


def test_arrow_keys_pick_a_command():
    async def test(app, pilot):
        await pilot.press(*"migrate", "down")
        assert app.screen.command.name == "sqlmigrate"
        assert app.screen.query_one(CommandLine).value == "sqlmigrate"
        # The list is still filtered by what was typed
        assert app.screen.query_one(CommandList).option_count == 3

    run_app(test)


def test_run_requires_arguments():
    async def test(app, pilot):
        await pilot.press(*"sqlmigrate", "enter")
        await pilot.pause()
        assert app.is_running
        assert [n.message for n in app._notifications] == ["Fill in app_label, migration_name first."]
        # Takes you to the first missing argument
        assert app.focused.parent.parent.parameter.label == "app_label"

    assert run_app(test) is None


def test_runs_in_process_and_returns(monkeypatch):
    ran = []
    monkeypatch.setattr(app_module, "run_and_wait", lambda args: ran.append(args) or 0)
    monkeypatch.setattr(DjangoTui, "suspend", lambda self: nullcontext())

    async def test(app, pilot):
        await pilot.press(*"showmigrations", "enter")
        await pilot.pause()
        assert app.is_running
        assert [n.message for n in app._notifications] == ["showmigrations finished."]

    assert run_app(test) is None
    assert ran == [["showmigrations"]]


def test_settings_option_needs_a_new_process():
    assert needs_new_process(["migrate", "--settings", "other"])
    assert needs_new_process(["migrate", "--pythonpath=src"])
    assert not needs_new_process(["migrate", "auth"])


def test_run_in_process(capsys):
    argv = sys.argv

    async def run():
        # Commands run in the TUI's event loop thread, the ORM must still work
        return run_in_process(["showmigrations", "auth"])

    assert asyncio.run(run()) == 0
    assert "0001_initial" in capsys.readouterr().out
    assert sys.argv is argv

    assert run_in_process(["sqlmigrate"]) == 2
    assert "the following arguments are required" in capsys.readouterr().err


def test_held_key_only_builds_the_final_form():
    async def test(app, pilot):
        for _ in range(5):
            app.screen.action_move("cursor_down")
            await asyncio.sleep(0.01)
        await pilot.pause(0.5)
        forms = app.screen.query(CommandForm)
        assert [form.command.name for form in forms] == [app.screen.command.name]

    run_app(test)


def test_common_options_are_added_when_expanded():
    async def test(app, pilot):
        await pilot.press(*"migrate", "tab")
        form = app.screen.query_one("#forms").visible_content
        assert isinstance(form, CommandForm)
        collapsible = form.query_one(Collapsible)
        assert not collapsible.query(ParameterField)

        collapsible.collapsed = False
        await pilot.pause()
        assert collapsible.query(ParameterField)

    run_app(test)


def test_switch_to_shell():
    async def test(app, pilot):
        assert isinstance(app.screen, CommandsScreen)
        await pilot.press("ctrl+j")
        assert isinstance(app.screen, ShellScreen)

        await pilot.press(*"6*7", "ctrl+r")
        assert app.screen.query_one("#output", TextArea).text == "42\n"

        await pilot.press("ctrl+j")
        assert isinstance(app.screen, CommandsScreen)

    run_app(test)


def test_open_shell():
    async def test(app, pilot):
        assert isinstance(app.screen, ShellScreen)

    run_app(test, open_shell=True)


def test_ctrl_c_twice_quits():
    async def test(app, pilot):
        await pilot.press("ctrl+c")
        assert app.is_running
        assert [n.message for n in app._notifications] == ["Press [b]ctrl+c[/] again to quit."]
        await pilot.press("ctrl+c")

    run_app(test)


def test_ctrl_c_copies_the_selection(monkeypatch):
    copied = []
    monkeypatch.setattr(app_module, "copy_to_clipboard", lambda app, text: copied.append(text))

    async def test(app, pilot):
        await pilot.press(*"migrate auth", "shift+left", "shift+left")
        await pilot.press("ctrl+c", "ctrl+c")
        assert app.is_running
        assert copied == ["th", "th"]

    run_app(test)

import asyncio

from trogon.widgets.command_tree import CommandTree

from django_tui.management.commands.ish import InteractiveShellScreen
from django_tui.management.commands.tui import DjangoTui, introspect_django_commands


def test_introspect_django_commands():
    commands = introspect_django_commands()

    assert "migrate" in commands["django"].subcommands
    assert "tui" in commands["django_tui"].subcommands


def test_tui():
    async def run():
        app = DjangoTui()
        async with app.run_test() as pilot:
            await pilot.press("down", "down")
            assert app.query_one(CommandTree).cursor_node.label.plain == "createsuperuser"

            await pilot.press("ctrl+j")
            assert isinstance(app.screen, InteractiveShellScreen)

    asyncio.run(run())

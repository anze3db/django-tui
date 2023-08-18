from typing import Any

from django.core.management import BaseCommand, get_commands, load_command_class


class Command(BaseCommand):
    help = """Run and inspect Django commands in a text-based user interface (TUI)."""

    def handle(self, *args: Any, **options: Any) -> None:
        for name, app_name in get_commands().items():
            print(name, load_command_class(app_name, name).help)

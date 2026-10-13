import os

from django.core.management import BaseCommand

# Like django-debug-toolbar's debugsqlshell, this command changes the process when its module is imported
os.environ["DJANGO_TUI_SIDE_EFFECT"] = "imported"


class Command(BaseCommand):
    help = "A command with a side effect on import."

    def handle(self, *args, **options):
        pass

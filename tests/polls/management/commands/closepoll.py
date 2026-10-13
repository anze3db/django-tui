from django.core.management.base import BaseCommand, CommandError
from polls.models import Question


class Command(BaseCommand):
    help = "Closes the specified polls for voting."

    def add_arguments(self, parser):
        parser.add_argument("poll_ids", nargs="+", type=int, help="IDs of the polls to close.")
        parser.add_argument("--delete", action="store_true", help="Delete the polls instead of closing them.")

    def handle(self, *args, **options):
        for poll_id in options["poll_ids"]:
            try:
                poll = Question.objects.get(pk=poll_id)
            except Question.DoesNotExist as e:
                raise CommandError(f'Poll "{poll_id}" does not exist') from e

            if options["delete"]:
                poll.delete()
                self.stdout.write(self.style.SUCCESS(f'Successfully deleted poll "{poll_id}"'))
            else:
                poll.is_open = False
                poll.save()
                self.stdout.write(self.style.SUCCESS(f'Successfully closed poll "{poll_id}"'))

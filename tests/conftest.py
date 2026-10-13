import django
from django.conf import settings


def pytest_configure():
    settings.configure(
        INSTALLED_APPS=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django_tui",
        ],
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
    )
    django.setup()

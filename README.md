# django-tui

Inspect and run Django Commands in a text-based user interface (TUI), built with [Textual](https://github.com/Textualize/textual).

[![PyPI - Version](https://img.shields.io/pypi/v/django-tui.svg)](https://pypi.org/project/django-tui)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/django-tui.svg)](https://pypi.org/project/django-tui)

![A demo of django-tui: filtering commands, filling in a command's options and running it, then querying models in the shell](https://raw.githubusercontent.com/anze3db/django-tui/main/docs/images/26.1/demo.gif)

## Commands

Type a command and its arguments, like in your shell, or fill in the form. Your project's commands are listed first.

![The command screen with the closepoll command and its options](https://raw.githubusercontent.com/anze3db/django-tui/main/docs/images/26.1/commands.png)

## Shell

Run ORM queries with your models and common Django helpers already imported.

![The shell with a query and its result](https://raw.githubusercontent.com/anze3db/django-tui/main/docs/images/26.1/shell.png)

## Installation

```console
pip install django-tui
```

Add `"django_tui"` to your `INSTALLED_APPS` setting in `settings.py` like this:


```python
INSTALLED_APPS = [
    ...,
    "django_tui",
]
```

Now you can run the TUI with:

```console
python manage.py tui
```

Type a command at the `$ python manage.py` prompt at the top, just like in your shell, e.g. `migrate myapp --plan`. The command name filters the list of commands and the arguments fill in the form below it. Changing the form updates the command too.

Press `enter` to run the command. It runs inside the TUI's process, so Django doesn't have to start up again for each one. When the command finishes, press `enter` to go back to the TUI.

| Key      | Action                                                  |
|----------|---------------------------------------------------------|
| `enter`  | Run the command                                         |
| `↑` `↓`  | Pick a command from the list                            |
| `→`      | Accept the suggested command name                       |
| `tab`    | Complete the command name and edit its options          |
| `ctrl+r` | Run the command (while editing options)                 |
| `ctrl+y` | Copy the command to the clipboard                       |
| `esc`    | Back to the command line, or clear it                   |
| `ctrl+j` | Switch between commands and the shell                   |
| `ctrl+c` | Copy the selected text, or press twice to quit          |

Open the interactive shell directly with `python manage.py tui --shell`. Press `ctrl+r` to run your code; the value of the last expression is shown in the output.

## Contributing

You need [uv](https://docs.astral.sh/uv/) and [just](https://just.systems/). `just` lists the tasks: `just check` lints and runs the tests, `just test-all` runs them on every supported Python and Django, and `just tui` opens the TUI in the test project. `just screenshots` and `just demo` save the images above for the next version, in `docs/images/<version>/`, and point this README at them. Keep the old images: PyPI shows each release's README with that release's images. Releases are described in [RELEASING.md](https://github.com/anze3db/django-tui/blob/main/RELEASING.md).

## License

`django-tui` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.

## Looking for Django Admin in your termain?

Checkout [@valberg](https://github.com/valberg)'s [django-admin-tui](https://github.com/valberg/django-admin-tui) project!


![Screenshot 2023-10-24 at 11 27 56](https://github.com/anze3db/django-tui/assets/513444/54bc6c84-267c-4e28-9d49-8b30391470ea)

# django-tui

Inspect and run Django Commands in a text-based user interface (TUI), built with [Textual](https://github.com/Textualize/textual).

[![PyPI - Version](https://img.shields.io/pypi/v/django-tui.svg)](https://pypi.org/project/django-tui)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/django-tui.svg)](https://pypi.org/project/django-tui)

-----

**Table of Contents**

- [Demo](#demo)
- [Installation](#installation)
- [Running](#running)
- [License](#license)

## 🎬 Demos

### Running Django Commands

https://github.com/anze3db/django-tui/assets/513444/fc84247a-9f4b-4017-9ae4-3f10fe9d9557

### Running ORM Queries in Interactive Django Shell

https://github.com/anze3db/django-tui/assets/513444/8a056da8-85a8-4086-9fa8-433b7346e787

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

You need [uv](https://docs.astral.sh/uv/) and [just](https://just.systems/). `just` lists the tasks: `just check` lints and runs the tests, `just test-all` runs them on every supported Python and Django, and `just tui` opens the TUI in the test project. Releases are described in [RELEASING.md](RELEASING.md).

## License

`django-tui` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.

## Looking for Django Admin in your termain?

Checkout [@valberg](https://github.com/valberg)'s [django-admin-tui](https://github.com/valberg/django-admin-tui) project!

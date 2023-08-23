# django-tui

Inspect and run Django Commands in a text-based user interface (TUI), built with [Textual](https://github.com/Textualize/textual) & [Trogon](https://github.com/Textualize/trogon).

[![PyPI - Version](https://img.shields.io/pypi/v/django-tui.svg)](https://pypi.org/project/django-tui)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/django-tui.svg)](https://pypi.org/project/django-tui)

-----

**Table of Contents**

- [Installation](#installation)
- [License](#license)

## Installation

```console
pip install django-tui
```

Add "django_tui" to your INSTALLED_APPS setting like this:


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

## License

`django-tui` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.

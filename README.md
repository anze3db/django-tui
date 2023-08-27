
![Screenshot 2023-08-27 at 06 57 45](https://github.com/anze3db/django-tui/assets/513444/11321700-9f22-4aa0-ad2b-1c1ac03c4b29)

# django-tui

Inspect and run Django Commands in a text-based user interface (TUI), built with [Textual](https://github.com/Textualize/textual) & [Trogon](https://github.com/Textualize/trogon).

[![PyPI - Version](https://img.shields.io/pypi/v/django-tui.svg)](https://pypi.org/project/django-tui)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/django-tui.svg)](https://pypi.org/project/django-tui)

-----

**Table of Contents**

- [Demo](#demo)
- [Installation](#installation)
- [Running](#running)
- [License](#license)

## 🎬 Demo

https://github.com/anze3db/django-tui/assets/513444/fc84247a-9f4b-4017-9ae4-3f10fe9d9557

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

## License

`django-tui` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.

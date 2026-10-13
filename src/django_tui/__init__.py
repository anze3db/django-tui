# SPDX-FileCopyrightText: 2023-present Anže Pečar <anze@pecar.me>
#
# SPDX-License-Identifier: MIT
from importlib import metadata as _metadata

try:
    __version__ = _metadata.version("django-tui")
except _metadata.PackageNotFoundError:  # running from a source tree without install
    __version__ = "0+unknown"

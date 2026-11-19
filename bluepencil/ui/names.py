# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""How files and folders are named on screen."""

from pathlib import Path


def display_folder(path: str) -> str:
    """The folder of `path`, with the home folder shown as ~."""
    folder = Path(path).parent
    home = Path.home()
    if folder == home:
        return "~"
    if folder.is_relative_to(home):
        return str(Path("~") / folder.relative_to(home))
    return str(folder)

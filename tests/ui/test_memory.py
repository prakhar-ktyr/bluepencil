# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Memory is given back when a window closes."""

import gc
from collections.abc import Callable

from bluepencil.window import BluepencilWindow

from .helpers import loaded
from .test_sidebar import show_sidebar, thumbnails_shown


def test_a_closed_window_is_freed_with_its_pages(run_app, make_pdf):
    # Closed windows used to stay in memory with every page they had
    # rendered: about 1 GB after a few files (see bluepencil/ui/weak.py).
    # GObject weak references: a Python one to a wrapper can go dead while
    # the object lives on (PyGObject 3.55 and later).
    references: list[Callable[[], object]] = []

    def close(window) -> None:
        references.extend(thing.weak_ref() for thing in (window, window.view, window.sidebar))
        # A second window keeps the app running once the first one closes.
        BluepencilWindow(application=window.get_application()).present()
        window.close()

    def freed(_window) -> bool:
        """the closed window, its pages and its thumbnails to be freed"""
        gc.collect()
        return all(reference() is None for reference in references)

    run_app(
        (loaded, show_sidebar),
        (thumbnails_shown, close),
        (freed, lambda _window: None),
        argv=[make_pdf(pages=20)],
    )

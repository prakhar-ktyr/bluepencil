# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Conditions and probes shared by the interface tests."""

import time

import gi

gi.require_version("Graphene", "1.0")
from gi.repository import Graphene  # noqa: E402


def loaded(window) -> bool:
    """the document to show its first page"""
    return window.view is not None and window.view.pages[0].texture is not None


def reading(index: int):
    """A condition: page `index` current in the page view, and drawn."""

    def condition(window) -> bool:
        view = window.view
        return (
            window._stack.get_visible_child() is window._split
            and view.current_page == index
            and view.pages[index].texture is not None
        )

    condition.__doc__ = f"page {index + 1} to be read"
    return condition


def after(seconds: float):
    """A condition met `seconds` after it is first checked: time enough for
    something that must not happen, such as a scroll, to show itself."""
    start: list[float] = []

    def condition(_window) -> bool:
        if not start:
            start.append(time.monotonic())
        return time.monotonic() - start[0] >= seconds

    condition.__doc__ = f"{seconds} seconds to pass"
    return condition


def scroll_position(window) -> float:
    return window.view._scroller.get_vadjustment().get_value()


def drawn_top(view, index: int) -> float:
    """Where page `index` is actually laid out, relative to the visible area."""
    _ok, point = view.pages[index].compute_point(view._scroller, Graphene.Point().init(0, 0))
    return point.y

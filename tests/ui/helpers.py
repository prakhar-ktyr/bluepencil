# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Conditions and probes shared by the interface tests."""

import gi

gi.require_version("Graphene", "1.0")
from gi.repository import Graphene  # noqa: E402


def loaded(window) -> bool:
    """the document to show its first page"""
    return window.view is not None and window.view.pages[0].texture is not None


def drawn_top(view, index: int) -> float:
    """Where page `index` is actually laid out, relative to the visible area."""
    _ok, point = view.pages[index].compute_point(view._scroller, Graphene.Point().init(0, 0))
    return point.y

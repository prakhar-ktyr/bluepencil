# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The app's own styles."""

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

_STYLES = """
.bp-page {
  background-color: white;
  box-shadow: 0 1px 3px alpha(black, 0.3), 0 0 0 1px alpha(black, 0.06);
}

/* The Combine list: each file's place in the order, on its picture. */
.bp-order-number {
  background-color: @accent_bg_color;
  color: @accent_fg_color;
  border-radius: 9999px;
  /* The size of the number itself: a circle, wider only past two digits. */
  min-width: 18px;
  min-height: 18px;
  padding: 0;
  font-weight: bold;
}

/* Where a dragged file will land. */
row.bp-drop-before {
  box-shadow: inset 0 2px @accent_color;
}

row.bp-drop-after {
  box-shadow: inset 0 -2px @accent_color;
}

row.bp-dragged {
  opacity: 0.4;
}
"""

#: Displays that have the styles already.
_styled: set[Gdk.Display] = set()


def load_styles() -> None:
    """Add the styles to the default display, once."""
    display = Gdk.Display.get_default()
    if display is None or display in _styled:
        return
    provider = Gtk.CssProvider()
    provider.load_from_string(_STYLES)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _styled.add(display)

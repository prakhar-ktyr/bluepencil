# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Split dialog: how to cut the document into several new PDFs."""

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GObject, Gtk  # noqa: E402

from ..core.ranges import every, parse_ranges  # noqa: E402
from ..i18n import _  # noqa: E402
from .weak import weakly  # noqa: E402


class SplitDialog(Adw.AlertDialog):
    """Asks how to split; emits split-requested with the groups of pages."""

    __gtype_name__ = "BluepencilSplitDialog"
    __gsignals__ = {
        # Lists of pages counted from 0, one list for each new file.
        "split-requested": (GObject.SignalFlags.RUN_LAST, None, (object,)),
    }

    def __init__(self, page_count: int) -> None:
        super().__init__(
            heading=_("Split Into Several Files"),
            body=_("Each part is saved as a new PDF. This document stays as it is."),
        )
        self.page_count = page_count

        self.every_choice = Gtk.CheckButton(label=_("Every"), active=True)
        self.size = Gtk.SpinButton.new_with_range(1, max(page_count, 1), 1)
        self.size.set_value(min(2, page_count))
        self.size.update_property([Gtk.AccessibleProperty.LABEL], [_("Pages in each file")])
        every_row = Gtk.Box(spacing=8)
        every_row.append(self.every_choice)
        every_row.append(self.size)
        every_row.append(Gtk.Label(label=_("pages")))

        self.ranges_choice = Gtk.CheckButton(label=_("By page ranges"), group=self.every_choice)
        self.ranges = Gtk.Entry(placeholder_text=_("For example 1-3, 4-10, 11-"), activates_default=True)
        self.ranges.update_property([Gtk.AccessibleProperty.LABEL], [_("Page ranges")])
        self.hint = Gtk.Label(xalign=0, wrap=True)
        self.hint.add_css_class("dim-label")
        self.hint.add_css_class("caption")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for widget in (every_row, self.ranges_choice, self.ranges, self.hint):
            content.append(widget)
        self.set_extra_child(content)

        self.add_response("cancel", _("_Cancel"))
        self.add_response("split", _("_Split…"))
        self.set_response_appearance("split", Adw.ResponseAppearance.SUGGESTED)
        self.set_default_response("split")
        self.set_close_response("cancel")

        for widget, signal in (
            (self.every_choice, "toggled"),
            (self.size, "value-changed"),
            (self.ranges, "changed"),
        ):
            widget.connect(signal, weakly(self._on_changed))
        self.ranges.connect("changed", weakly(self._on_ranges_typed))
        self.connect("response", self._on_response)
        self._on_changed()

    def groups(self) -> list[list[int]] | None:
        """The pages of each new file, or None if the choice is not valid."""
        try:
            if self.every_choice.get_active():
                return every(self.size.get_value_as_int(), self.page_count)
            return parse_ranges(self.ranges.get_text(), self.page_count)
        except ValueError:
            return None

    def _on_ranges_typed(self, *_args: object) -> None:
        self.ranges_choice.set_active(True)

    def _on_changed(self, *_args: object) -> None:
        groups = self.groups()
        self.set_response_enabled("split", groups is not None)
        if groups is None:
            self.hint.set_label(_("Pages go from 1 to {count}.").format(count=self.page_count))
        else:
            self.hint.set_label(_("{files} new files.").format(files=len(groups)))

    def _on_response(self, _dialog: Adw.AlertDialog, response: str) -> None:
        groups = self.groups()
        if response == "split" and groups is not None:
            self.emit("split-requested", groups)

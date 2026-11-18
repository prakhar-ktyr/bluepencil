# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The main window: header bar, Open button and the document area.

Written against GTK 4.6 and libadwaita 1.1 (Ubuntu 22.04), so it avoids
newer widgets such as Adw.ToolbarView and Gtk.FileDialog.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk  # noqa: E402

from . import APP_NAME  # noqa: E402


class BluepencilWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.set_title(APP_NAME)
        self.set_default_size(1000, 700)

        self.current_file: Gio.File | None = None
        # Gtk.FileChooserNative is not kept alive by GTK itself; without this
        # reference Python frees it and the dialog never answers.
        self._chooser: Gtk.FileChooserNative | None = None

        open_action = Gio.SimpleAction.new("open", None)
        open_action.connect("activate", self._on_open_clicked)
        self.add_action(open_action)

        self._title = Adw.WindowTitle(title=APP_NAME)

        header = Adw.HeaderBar(title_widget=self._title)
        header.pack_start(Gtk.Button(label="Open", action_name="win.open"))
        header.pack_end(self._build_menu_button())

        self._status = Adw.StatusPage(
            icon_name="x-office-document-symbolic",
            title="Open a PDF",
            description="Choose a file to get started.",
            vexpand=True,
        )
        open_button = Gtk.Button(
            label="Open PDF…",
            action_name="win.open",
            halign=Gtk.Align.CENTER,
        )
        open_button.add_css_class("pill")
        open_button.add_css_class("suggested-action")
        self._status.set_child(open_button)

        self._toasts = Adw.ToastOverlay(child=self._status)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(header)
        content.append(self._toasts)
        self.set_content(content)

    def open_file(self, file: Gio.File) -> None:
        """Make `file` the window's current document."""
        name = file.get_basename() or "Untitled"
        if not name.lower().endswith(".pdf"):
            self._toasts.add_toast(Adw.Toast(title=f"“{name}” is not a PDF"))
            return

        self.current_file = file
        self._title.set_subtitle(name)
        self._status.set_title(name)
        self._status.set_description("Opened. The page view is the next feature.")

    def _build_menu_button(self) -> Gtk.MenuButton:
        menu = Gio.Menu()
        menu.append(f"About {APP_NAME}", "app.about")
        menu.append("Quit", "app.quit")
        return Gtk.MenuButton(
            icon_name="open-menu-symbolic",
            menu_model=menu,
            tooltip_text="Main Menu",
        )

    def _on_open_clicked(self, *_args: object) -> None:
        pdf_filter = Gtk.FileFilter()
        pdf_filter.set_name("PDF documents")
        pdf_filter.add_mime_type("application/pdf")
        pdf_filter.add_pattern("*.pdf")

        self._chooser = Gtk.FileChooserNative.new(
            "Open PDF", self, Gtk.FileChooserAction.OPEN, "_Open", "_Cancel"
        )
        self._chooser.set_modal(True)
        self._chooser.add_filter(pdf_filter)
        self._chooser.connect("response", self._on_chooser_response)
        self._chooser.show()

    def _on_chooser_response(
        self, chooser: Gtk.FileChooserNative, response: int
    ) -> None:
        file = chooser.get_file() if response == Gtk.ResponseType.ACCEPT else None
        self._chooser = None
        if file is not None:
            self.open_file(file)

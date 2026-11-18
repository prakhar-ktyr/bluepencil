# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The main window: header bar, Open button and the document area."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import APP_NAME  # noqa: E402


class BluepencilWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.set_title(APP_NAME)
        self.set_default_size(1000, 700)

        self.current_file: Gio.File | None = None

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

        toolbar = Adw.ToolbarView(content=self._toasts)
        toolbar.add_top_bar(header)
        self.set_content(toolbar)

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
        pdf_filter = Gtk.FileFilter(name="PDF documents")
        pdf_filter.add_mime_type("application/pdf")
        pdf_filter.add_suffix("pdf")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(pdf_filter)

        dialog = Gtk.FileDialog(
            title="Open PDF",
            modal=True,
            filters=filters,
            default_filter=pdf_filter,
        )
        dialog.open(self, None, self._on_file_chosen)

    def _on_file_chosen(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            file = dialog.open_finish(result)
        except GLib.Error as error:
            # Closing the dialog without choosing a file is not an error.
            if not error.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                self._toasts.add_toast(Adw.Toast(title=f"Could not open the file: {error.message}"))
            return
        if file is not None:
            self.open_file(file)

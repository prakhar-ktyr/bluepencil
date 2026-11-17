"""The application object: owns the window, app-wide actions and shortcuts."""

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, APP_SUMMARY, VERSION  # noqa: E402
from .window import BluepencilWindow  # noqa: E402


class BluepencilApplication(Adw.Application):
    def __init__(self) -> None:
        # HANDLES_OPEN lets "Open With Bluepencil" in the file manager and
        # `bluepencil file.pdf` on the command line reach do_open().
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )
        self._add_action("about", self._on_about)
        self._add_action("quit", lambda *_: self.quit(), ["<primary>q"])
        self.set_accels_for_action("win.open", ["<primary>o"])

    def do_activate(self) -> None:
        self._get_window().present()

    def do_open(self, files: list[Gio.File], n_files: int, hint: str) -> None:
        window = self._get_window()
        window.present()
        # One document per window for now; extra files are ignored.
        window.open_file(files[0])

    def _get_window(self) -> BluepencilWindow:
        window = self.props.active_window
        if window is None:
            window = BluepencilWindow(application=self)
        return window

    def _add_action(
        self,
        name: str,
        callback: Callable[..., None],
        shortcuts: list[str] | None = None,
    ) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)

    def _on_about(self, *_args: object) -> None:
        # Gtk.AboutDialog, not Adw.AboutWindow: Ubuntu 22.04 ships
        # libadwaita 1.1 and AboutWindow needs 1.2.
        about = Gtk.AboutDialog(
            transient_for=self.props.active_window,
            modal=True,
            program_name=APP_NAME,
            version=VERSION,
            comments=APP_SUMMARY,
            logo_icon_name="x-office-document",
        )
        about.present()

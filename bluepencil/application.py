# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The application object: windows, app-wide actions and shortcuts."""

from collections.abc import Callable

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, APP_SUMMARY, COPYRIGHT, VERSION  # noqa: E402
from .core.memory import release_memory_promptly  # noqa: E402
from .history import History  # noqa: E402
from .i18n import _  # noqa: E402
from .recovery import Recoverable, discard, find_recoverable  # noqa: E402
from .ui.styles import load_styles  # noqa: E402
from .window import BluepencilWindow  # noqa: E402

#: Keyboard shortcuts for window actions.
_SHORTCUTS = {
    "win.open": ["<primary>o"],
    "win.zoom-in": ["<primary>plus", "<primary>equal", "<primary>KP_Add"],
    "win.zoom-out": ["<primary>minus", "<primary>KP_Subtract"],
    "win.zoom-fit-width": ["<primary>0"],
    "win.go-to-page": ["<primary>l"],
    "win.toggle-sidebar": ["F9"],
    "win.save": ["<primary>s"],
    "win.save-as": ["<primary><shift>s"],
    "win.undo": ["<primary>z"],
    "win.redo": ["<primary><shift>z", "<primary>y"],
    "win.rotate-left": ["<primary>bracketleft"],
    "win.rotate-right": ["<primary>bracketright"],
    "win.organize": ["<primary>g"],
}


def build_about_dialog() -> Adw.AboutDialog:
    """The About window.

    It also carries the notice the AGPL asks interactive programs to show:
    the copyright, that there is no warranty, and which licence applies.
    """
    return Adw.AboutDialog(
        application_name=APP_NAME,
        application_icon="x-office-document",
        version=VERSION,
        comments=_(APP_SUMMARY),
        copyright=COPYRIGHT,
        license_type=Gtk.License.AGPL_3_0,
    )


class BluepencilApplication(Adw.Application):
    def __init__(self) -> None:
        # HANDLES_OPEN lets "Open With Bluepencil" in the file manager and
        # `bluepencil file.pdf` on the command line reach do_open().
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        release_memory_promptly()
        #: Recent files and where the reader left each one, for every window.
        self.history = History()
        #: Changes to offer back after a crash; looked for once, at startup.
        self._recoverable: list[Recoverable] | None = None
        self._add_action("about", self._on_about)
        self._add_action("quit", self._on_quit, ["<primary>q"])
        for action, shortcuts in _SHORTCUTS.items():
            self.set_accels_for_action(action, shortcuts)

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        load_styles()

    def do_activate(self) -> None:
        window = self.props.active_window or BluepencilWindow(application=self)
        window.present()
        self._offer_recovery(window)

    def do_open(self, files: list[Gio.File], n_files: int, hint: str) -> None:
        for file in files:
            self.open_file(file)

    def do_shutdown(self) -> None:
        for window in self.get_windows():
            if isinstance(window, BluepencilWindow):
                window.shutdown()
        self.history.save()
        Adw.Application.do_shutdown(self)

    def open_file(self, file: Gio.File, window: BluepencilWindow | None = None) -> None:
        """Show `file` in `window` if it is empty, otherwise in an empty or new window."""
        if window is None or not window.is_empty:
            window = next(
                (w for w in self.get_windows() if isinstance(w, BluepencilWindow) and w.is_empty),
                None,
            )
        if window is None:
            window = BluepencilWindow(application=self)
        window.present()
        window.open_file(file)
        self._offer_recovery(window)

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

    def _offer_recovery(self, window: BluepencilWindow) -> None:
        """Once per run: offer changes left unsaved when Bluepencil last stopped."""
        if self._recoverable is not None:
            return
        self._recoverable = find_recoverable()
        if not self._recoverable:
            return
        names = "\n".join(f"• {item.name}" for item in self._recoverable)
        dialog = Adw.AlertDialog(
            heading=_("Recover Unsaved Changes?"),
            body=_("Bluepencil stopped before these changes were saved:\n{names}").format(names=names),
        )
        dialog.add_response("discard", _("_Discard"))
        dialog.add_response("recover", _("_Recover"))
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("recover", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("recover")
        dialog.set_close_response("recover")  # closing it keeps them for next time
        dialog.connect("response", self._on_recovery_response)
        dialog.present(window)

    def _on_recovery_response(self, _dialog: Adw.AlertDialog, response: str) -> None:
        items, self._recoverable = self._recoverable or [], []
        for item in items:
            if response == "discard":
                discard(item)
                continue
            window = next(
                (w for w in self.get_windows() if isinstance(w, BluepencilWindow) and w.is_empty),
                None,
            ) or BluepencilWindow(application=self)
            window.present()
            window.recover(item)

    def _on_quit(self, *_args: object) -> None:
        # Closing each window lets those with unsaved changes ask first; the
        # app ends when the last one has closed.
        for window in list(self.get_windows()):
            window.close()

    def _on_about(self, *_args: object) -> None:
        build_about_dialog().present(self.props.active_window)

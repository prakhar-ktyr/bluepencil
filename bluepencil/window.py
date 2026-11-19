# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The main window: header bar, the open document, and the bar below it."""

import functools
import inspect
import shutil
import time
import weakref
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_NAME  # noqa: E402
from .core.places import jobs_root  # noqa: E402
from .engine_client import EngineClient  # noqa: E402
from .history import History  # noqa: E402
from .i18n import _  # noqa: E402
from .recovery import Recoverable  # noqa: E402
from .ui.combine_dialog import CombineDialog, files_filter  # noqa: E402
from .ui.compress_dialog import CompressDialog  # noqa: E402
from .ui.document_view import DocumentView, FitMode  # noqa: E402
from .ui.names import display_folder  # noqa: E402
from .ui.organize import OrganizeView  # noqa: E402
from .ui.split_dialog import SplitDialog  # noqa: E402
from .ui.thumbnails import ThumbnailSidebar  # noqa: E402
from .ui.weak import weakly  # noqa: E402

#: Zoom levels in the zoom menu, in percent.
ZOOM_PRESETS = (50, 100, 150, 200, 400)
#: A file that stops the engine more often than this within RESTART_PERIOD
#: seconds is given up on.
MAX_RESTARTS = 3
RESTART_PERIOD = 30.0
#: Opening is usually instant, so "Opening…" only appears after this delay.
LOADING_DELAY_MS = 300
#: Recent files listed on the start page.
RECENT_SHOWN = 10
#: Engine priorities (lower goes first; page renders are 0 and up). Opening
#: comes before anything else, and edits before renders of the old pages.
OPEN_PRIORITY = -2
EDIT_PRIORITY = -1

#: Actions that change pages: in Organize mode they act on the selected
#: pages, otherwise on the current page.
_PAGE_ACTIONS = (
    "rotate-left",
    "rotate-right",
    "delete-page",
    "duplicate-pages",
    "extract-pages",
    "insert-blank",
    "insert-files",
)

_DOCUMENT_ACTIONS = (
    "zoom-in",
    "zoom-out",
    "zoom-fit-width",
    "zoom-fit-page",
    "zoom-percent",
    "go-to-page",
    "toggle-sidebar",
)


def _open_error_message(code: str | None) -> str:
    messages = {
        "not-found": _("The file doesn’t exist any more."),
        "no-permission": _("You don’t have permission to read this file."),
        "damaged": _("The file is damaged, or it isn’t a PDF."),
        "not-pdf": _("The file isn’t a PDF, even though its name may say so."),
        "no-pages": _("The file has no pages."),
        "engine-failed": _("Bluepencil’s PDF engine kept stopping while reading this file."),
        "unsupported-file": _("Only PDFs and pictures can be combined."),
        "needs-password": _("One of the files is password-protected."),
    }
    return messages.get(code or "", _("Something went wrong while opening the file."))


def _edit_error_message(code: str | None) -> str:
    messages = {
        "no-pages-left": _("A document needs at least one page."),
        "no-permission": _("You don’t have permission to save in this folder. Use Save As to save a copy elsewhere."),
        "read-only": _("This location is read-only. Use Save As to save a copy elsewhere."),
        "disk-full": _("The disk is full. Free some space, or save the file somewhere else."),
        "check-failed": _("The saved file could not be read back, so the original was kept as it was."),
        "unsupported-file": _("Only PDFs and pictures can be added to a document."),
        "needs-password": _("One of the files is password-protected. Combine Files can unlock it."),
        "damaged": _("One of the files is damaged."),
        "write-failed": _("The file could not be written. The original was kept as it was."),
    }
    return messages.get(code or "", _("That did not work, and nothing was changed."))


def _display_name(file: Gio.File) -> str:
    return file.get_basename() or _("Untitled")


def _free_path(folder: Path, stem: str) -> Path:
    """`folder/stem.pdf`, or `stem (2).pdf` and so on if that is taken."""
    path, number = folder / f"{stem}.pdf", 2
    while path.exists():
        path, number = folder / f"{stem} ({number}).pdf", number + 1
    return path


class BluepencilWindow(Adw.ApplicationWindow):
    __gtype_name__ = "BluepencilWindow"

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.set_title(APP_NAME)
        self.set_default_size(1000, 760)
        self._init_state()
        self._add_actions()
        self._title = Adw.WindowTitle(title=APP_NAME)
        self._build_window_content()

    def _init_state(self) -> None:
        #: The file on show, once it has opened.
        self.current_file: Gio.File | None = None
        #: The page view and the thumbnails, while a file is on show.
        self.view: DocumentView | None = None
        self.sidebar: ThumbnailSidebar | None = None
        self._engine: EngineClient | None = None
        self._loading: Gio.File | None = None
        self._loading_password: str | None = None
        #: History to carry on from, when recovering changes after a crash.
        self._loading_history: dict | None = None
        #: The file whose password dialog is open.
        self._asking: Gio.File | None = None
        self._password: str | None = None
        self._restarts: list[float] = []
        #: Page sizes of the file on show, for the thumbnails.
        self._page_sizes: list[tuple[float, float]] = []
        #: What the engine last said about the document: pages, history,
        #: whether it has unsaved changes.
        self._state: dict = {}
        #: An edit or a save is on its way to the engine; others wait.
        self._busy = False
        self._close_after_save = False
        self._discard_confirmed = False
        #: The page grid, while Organize mode is on.
        self.organize: OrganizeView | None = None
        #: The Compress dialog, while it is open.
        self.compress_dialog: CompressDialog | None = None
        #: The Combine list, while it is open.
        self.combine_dialog: CombineDialog | None = None
        #: The files being combined here, and their passwords, until the
        #: new document shows.
        self._combining: tuple[list[str], dict[str, str]] | None = None
        self._actions: dict[str, Gio.SimpleAction] = {}
        #: Rows of the recent files list, with the path each one opens.
        self._recent_rows: list[tuple[str, Adw.ActionRow]] = []
        self._history_handler = 0

    def _build_window_content(self) -> None:
        header = self._build_header()

        self._status = self._build_status_page()

        # The open document: thumbnails beside the pages. In narrow windows
        # the thumbnails slide over the pages instead.
        self._split = Adw.OverlaySplitView(show_sidebar=False, min_sidebar_width=170, max_sidebar_width=220)
        self._split.connect("notify::show-sidebar", weakly(self._on_sidebar_shown))

        self._stack = Gtk.Stack()
        self._stack.add_named(self._status, "status")
        self._stack.add_named(self._split, "document")
        self._toasts = Adw.ToastOverlay(child=self._stack)

        self._toolbar = Adw.ToolbarView(content=self._toasts, reveal_bottom_bars=False)
        self._toolbar.add_top_bar(header)
        self._bottom_bar = self._build_bottom_bar()
        self._toolbar.add_bottom_bar(self._bottom_bar)
        self._organize_bar = self._build_organize_bar()
        self._organize_bar.set_visible(False)
        self._toolbar.add_bottom_bar(self._organize_bar)
        self.set_content(self._toolbar)
        self._show_start()

        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 600sp"))
        narrow.add_setter(self._split, "collapsed", True)
        # Everything must fit in the narrowest window, 360 pixels.
        narrow.add_setter(self._open_header_button, "visible", False)
        narrow.add_setter(self._save_button, "visible", False)
        narrow.add_setter(self._save_icon_button, "visible", True)
        narrow.add_setter(self._extract_button, "visible", False)
        narrow.add_setter(self._split_button, "visible", False)
        narrow.add_setter(self._more_pages_button, "visible", True)
        self.add_breakpoint(narrow)
        self.set_size_request(360, 400)  # windows with breakpoints need a minimum size

        # Start the PDF engine while the user picks a file: loading the PDF
        # library takes about a third of a second.
        GLib.idle_add(self._start_engine_early)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", weakly(self._on_drop))
        self.add_controller(drop)
        self.connect("close-request", self._on_close_request)

    @property
    def is_empty(self) -> bool:
        """True when no file is on show, on its way, or waiting for a password."""
        return self.current_file is None and self._loading is None and self._asking is None

    def open_file(self, file: Gio.File) -> None:
        """Show `file` here. BluepencilApplication.open_file picks the window."""
        if file.get_path() is None:
            self._toast(_("Only files on this computer can be opened"))
            return
        self._restarts = []
        self._load(file, None)

    def shutdown(self) -> None:
        """Stop the engine. Runs when the window closes or the app quits."""
        if self.combine_dialog is not None:
            self.combine_dialog.force_close()  # its engine stops with it
        self._remember_position()
        if self._history_handler:
            self._history.disconnect(self._history_handler)
            self._history_handler = 0
        if self._engine is not None:
            # Changes neither saved nor discarded, as when the app is stopped
            # without asking, stay recoverable.
            unsaved = bool(self._state.get("modified")) and not self._discard_confirmed
            self._engine.close(keep_snapshots=unsaved)
            self._engine = None

    @property
    def _history(self) -> History:
        return self.get_application().history

    # Opening

    def recover(self, item: Recoverable) -> None:
        """Open the changes Bluepencil kept when it stopped unexpectedly."""
        self._restarts = []
        self._loading_history = item.history
        self._load(Gio.File.new_for_path(item.path), None)

    def _load(self, file: Gio.File, password: str | None) -> None:
        self._loading = file
        self._loading_password = password
        engine = self._ensure_engine()
        engine.request(
            {"op": "open", "path": file.get_path(), "password": password, "history": self._loading_history},
            functools.partial(self._on_opened, file, password),
            key=("open",),
            priority=OPEN_PRIORITY,
        )
        GLib.timeout_add(LOADING_DELAY_MS, self._show_loading, file)

    def _start_engine_early(self) -> bool:
        if self.get_application() is not None:  # not closed in the meantime
            self._ensure_engine()
        return GLib.SOURCE_REMOVE

    def combine_files(self, paths: list[str], passwords: dict[str, str] | None = None) -> None:
        """Make a new document from these PDFs and pictures, in this order.
        `passwords` unlocks locked PDFs, by path."""
        if not paths:
            return
        self._restarts = []
        self._combine(paths, passwords or {})

    def _combine(self, paths: list[str], passwords: dict[str, str]) -> None:
        target = _free_path(Path(paths[0]).parent, _("Combined"))
        file = Gio.File.new_for_path(str(target))
        self._combining = (paths, passwords)
        self._loading = file
        self._loading_password = None
        self._ensure_engine().request(
            {"op": "combine", "paths": paths, "path": str(target), "passwords": passwords},
            functools.partial(self._on_combined, file),
            key=("open",),
            priority=OPEN_PRIORITY,
        )
        GLib.timeout_add(LOADING_DELAY_MS, self._show_loading, file)

    def _on_combined(self, file: Gio.File, reply: dict, _payload: bytes) -> None:
        if file is not self._loading:
            return  # another file was asked for in the meantime
        self._loading = None
        self._combining = None
        if reply.get("ok"):
            self._show_document(file, None, reply)
        else:
            self._show_combine_error(reply.get("error"))

    def _show_combine_error(self, code: str | None) -> None:
        self._close_document()
        message = _open_error_message(code)
        self._show_status("dialog-warning-symbolic", _("Can’t Combine the Files"), message, show_button=True)

    def show_combine_list(self, paths: list[str]) -> CombineDialog:
        """Show files in the Combine list, to put in order and add to before
        combining. Files join the list if it is open already."""
        if self.combine_dialog is not None:
            self.combine_dialog.add_files(paths)
            return self.combine_dialog
        dialog = CombineDialog(paths)
        dialog.connect("combine-requested", weakly(self._on_combine_requested))
        dialog.connect("closed", weakly(self._on_combine_dialog_closed))
        self.combine_dialog = dialog
        dialog.present(self)
        dialog.set_focus(dialog.combine_button)  # Enter combines, when the order is right
        return dialog

    def _on_combine_requested(self, dialog: CombineDialog, paths: list[str], passwords: dict[str, str]) -> None:
        dialog.close()
        if self.is_empty:
            self.combine_files(paths, passwords)
        else:
            window = type(self)(application=self.get_application())
            window.present()
            window.combine_files(paths, passwords)

    def _on_combine_dialog_closed(self, dialog: CombineDialog) -> None:
        if self.combine_dialog is dialog:
            self.combine_dialog = None

    def _on_combine_clicked(self, *_args: object) -> None:
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(files_filter())
        dialog = Gtk.FileDialog(title=_("Combine Files"), modal=True, filters=filters)
        dialog.open_multiple(self, None, weakly(self._on_combine_chosen))

    def _on_combine_chosen(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return  # closed without choosing
        paths = [path for file in files if (path := file.get_path()) is not None]
        if paths:
            self.show_combine_list(paths)

    def _ensure_engine(self) -> EngineClient:
        if self._engine is None:
            self._engine = EngineClient()
            self._engine.connect("died", weakly(self._on_engine_died))
        self._engine.start()
        return self._engine

    def _show_loading(self, file: Gio.File) -> bool:
        if self._loading is file and self.view is None:
            title = _("Opening “{name}”…").format(name=_display_name(file))
            self._show_status("document-open-symbolic", title, "", show_button=False)
        return GLib.SOURCE_REMOVE

    def _on_opened(self, file: Gio.File, password: str | None, reply: dict, _payload: bytes) -> None:
        if file is not self._loading:
            return  # another file was asked for in the meantime
        self._loading = None
        error = reply.get("error")
        if error not in ("needs-password", "wrong-password"):
            self._loading_history = None  # used, or of no use
        if reply.get("ok"):
            self._show_document(file, password, reply)
        elif error in ("needs-password", "wrong-password"):
            self._ask_password(file, wrong=error == "wrong-password")
        else:
            self._show_error(file, error)

    def _show_document(self, file: Gio.File, password: str | None, info: dict) -> None:
        engine = self._ensure_engine()
        path = file.get_path()
        # Back to where the reader left this file last time.
        place = self._history.lookup(path)
        size = self._expected_view_size()
        if place is not None:
            view = DocumentView(
                engine, info["pages"], zoom=place.zoom, fit=place.fit, page=place.page, size_hint=size
            )
        else:
            view = DocumentView(engine, info["pages"], size_hint=size)
        if not info.get("untitled") and Path(path).exists():
            self._history.opened(path)
        view.connect("current-page-changed", weakly(self._on_current_page_changed))
        view.connect("zoom-changed", weakly(self._on_zoom_changed))
        self._on_zoom_changed(view)
        self.view = view
        self.current_file = file
        self._password = password
        self._page_sizes = info["pages"]
        self._state = info
        self._split.set_content(view)
        if self._split.get_show_sidebar():
            self._build_sidebar()
        self._stack.set_visible_child(self._split)

        self._update_title()
        self._page_total.set_label(_("of {count}").format(count=info["page_count"]))
        self._page_entry.set_text(str(view.current_page + 1))
        self._on_zoom_changed(view)
        self._toolbar.set_reveal_bottom_bars(True)
        self._set_document_actions(True)
        self._update_edit_actions()
        view.focus_pages()
        if info.get("untitled"):
            # Combined files: put the pages in order first.
            self._actions["organize"].change_state(GLib.Variant.new_boolean(True))
        if info.get("repaired"):
            self._toast(_("This file is damaged. Bluepencil repaired it for viewing; the file itself is unchanged."))

    def _build_sidebar(self) -> None:
        """Make the thumbnails, the first time they are shown for this file.

        Even hidden, the list would prepare about 200 rows, which made opening
        a file slower for people who never look at the thumbnails.
        """
        if self.sidebar is not None or self.view is None or self._engine is None:
            return
        sidebar = ThumbnailSidebar(self._engine, self._page_sizes)
        sidebar.connect("page-chosen", weakly(self._on_page_chosen))
        sidebar.set_open(self._split.get_show_sidebar())
        sidebar.show_page(self.view.current_page)
        self.sidebar = sidebar
        self._split.set_sidebar(sidebar)

    def _expected_view_size(self) -> tuple[int, int]:
        """The size the page view will get, worked out before it is shown."""
        width, height = self._stack.get_width(), self._stack.get_height()
        if self._split.get_show_sidebar() and not self._split.get_collapsed():
            fraction = self._split.get_sidebar_width_fraction()
            low, high = self._split.get_min_sidebar_width(), self._split.get_max_sidebar_width()
            width -= round(min(max(width * fraction, low), high))
        if not self._toolbar.get_reveal_bottom_bars():
            height -= self._bottom_bar.get_preferred_size()[1].height
        return max(width, 0), max(height, 0)

    def _ask_password(self, file: Gio.File, wrong: bool) -> None:
        entry = Gtk.PasswordEntry(show_peek_icon=True, activates_default=True)
        entry.update_property([Gtk.AccessibleProperty.LABEL], [_("Password")])
        if wrong:
            body = _("That password is not correct. Try again.")
        else:
            body = _("“{name}” is protected. Enter its password to open it.").format(name=_display_name(file))
        dialog = Adw.AlertDialog(heading=_("Password Required"), body=body)
        dialog.add_response("cancel", _("_Cancel"))
        dialog.add_response("open", _("_Open"))
        dialog.set_response_appearance("open", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("open")
        dialog.set_close_response("cancel")
        dialog.set_extra_child(entry)
        dialog.connect("response", weakly(self._on_password_response), file, entry)
        self._asking = file
        dialog.present(self)
        dialog.set_focus(entry)

    def _on_password_response(
        self, _dialog: Adw.AlertDialog, response: str, file: Gio.File, entry: Gtk.PasswordEntry
    ) -> None:
        self._asking = None
        if response == "open":
            self._load(file, entry.get_text())
        elif self.current_file is None:
            self._show_start()

    def _show_error(self, file: Gio.File, code: str | None) -> None:
        if code == "not-found":
            self._history.forget(file.get_path())
        self._close_document()
        title = _("Can’t Open “{name}”").format(name=_display_name(file))
        self._show_status("dialog-warning-symbolic", title, _open_error_message(code), show_button=True)

    def _close_document(self) -> None:
        self._remember_position()
        if self._organize_on:
            self._actions["organize"].change_state(GLib.Variant.new_boolean(False))
        self._drop_organize()
        self._split.set_content(None)
        self._split.set_sidebar(None)
        self.view = None
        self.sidebar = None
        self.current_file = None
        self._password = None
        self._state = {}
        self._busy = False
        self._title.set_subtitle("")
        self.set_title(APP_NAME)
        self._toolbar.set_reveal_bottom_bars(False)
        self._set_document_actions(False)
        self._update_edit_actions()

    def _show_start(self) -> None:
        self._show_status(
            "x-office-document-symbolic",
            _("Open a PDF"),
            _("Choose a file, or drop one here."),
            show_button=True,
            show_recent=True,
        )

    def _show_status(
        self, icon: str, title: str, description: str, show_button: bool, show_recent: bool = False
    ) -> None:
        self._status.set_icon_name(icon)
        self._status.set_title(title)
        self._status.set_description(description)
        self._open_button.set_visible(show_button)
        self._combine_button.set_visible(show_recent)
        self._recent_shown = show_recent
        self._refresh_recent_files()
        self._stack.set_visible_child(self._status)

    # Recent files

    def _build_recent_files(self) -> Adw.PreferencesGroup:
        self._recent_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._recent_list.add_css_class("boxed-list")
        self._recent_list.update_property([Gtk.AccessibleProperty.LABEL], [_("Recent Files")])
        clear = Gtk.Button(label=_("_Clear List"), use_underline=True, valign=Gtk.Align.CENTER)
        clear.add_css_class("flat")
        clear.connect("clicked", weakly(self._on_clear_recent))
        self._recent_group = Adw.PreferencesGroup(title=_("Recent Files"), header_suffix=clear)
        self._recent_group.add(self._recent_list)
        self._recent_shown = False
        self._history_handler = self._history.connect("changed", weakly(self._refresh_recent_files))
        return self._recent_group

    def _on_clear_recent(self, _button: Gtk.Button) -> None:
        self._history.clear()

    def _on_forget_recent(self, _button: Gtk.Button, path: str) -> None:
        self._history.forget(path)

    def _refresh_recent_files(self, *_args: object) -> None:
        entries = self._history.recent()[:RECENT_SHOWN] if self._recent_shown else []
        self._recent_list.remove_all()
        self._recent_rows = []
        for entry in entries:
            name = Path(entry.path).name
            # use_markup off: a file name is shown as it is, "&" and all.
            row = Adw.ActionRow(
                title=name,
                subtitle=display_folder(entry.path),
                use_markup=False,
                activatable=True,
                title_lines=1,
                subtitle_lines=1,
            )
            row.set_tooltip_text(entry.path)  # the full path, when the row cuts it short
            # "activated" covers a click, Enter, and the row's own activate().
            row.connect("activated", weakly(self._on_recent_activated), entry.path)
            remove = Gtk.Button(icon_name="window-close-symbolic", valign=Gtk.Align.CENTER)
            remove.set_tooltip_text(_("Remove From List"))
            remove.update_property(
                [Gtk.AccessibleProperty.LABEL], [_("Remove “{name}” from the list").format(name=name)]
            )
            remove.add_css_class("flat")
            remove.connect("clicked", weakly(self._on_forget_recent), entry.path)
            row.add_suffix(remove)
            self._recent_list.append(row)
            self._recent_rows.append((entry.path, row))
        self._recent_group.set_visible(bool(entries))

    def _on_recent_activated(self, _row: Adw.ActionRow, path: str) -> None:
        self.get_application().open_file(Gio.File.new_for_path(path), self)

    def _remember_position(self) -> None:
        if self.view is not None and self.current_file is not None:
            self._history.remember_position(
                self.current_file.get_path(), self.view.current_page, self.view.zoom, self.view.fit_mode
            )

    # Engine crashes

    def _on_engine_died(self, engine: EngineClient) -> None:
        file = self.current_file or self._loading
        if file is None:
            return  # nothing on show; the engine starts again when needed
        now = time.monotonic()
        self._restarts = [t for t in self._restarts if now - t < RESTART_PERIOD] + [now]
        if len(self._restarts) > MAX_RESTARTS:
            self._loading = None
            if self.current_file is None and self._combining is not None:
                self._combining = None
                self._show_combine_error("engine-failed")
            else:
                self._show_error(file, "engine-failed")
            return
        self._toast(_("The PDF engine stopped unexpectedly and was restarted"))
        if self.current_file is None and self._combining is not None:
            self._combine(*self._combining)
            return
        if self.current_file is None:
            self._load(file, self._loading_password)
            return
        engine.start()
        # The history lets the new engine carry on from the last edit's
        # snapshot, with undo and redo as they were.
        engine.request(
            {"op": "open", "path": file.get_path(), "password": self._password, "history": self._state.get("history")},
            functools.partial(self._on_reopened, file),
            key=("open",),
            priority=OPEN_PRIORITY,
        )
        self._busy = False  # an edit on its way died with the engine
        self._close_after_save = False
        self._update_edit_actions()
        if self.view is not None:
            self.view.restart_rendering()
        if self.sidebar is not None:
            self.sidebar.restart_rendering()

    def _on_reopened(self, file: Gio.File, reply: dict, _payload: bytes) -> None:
        if file is not self.current_file:
            return
        if not reply.get("ok"):
            self._show_error(file, reply.get("error"))
            return
        if reply["pages"] != self._page_sizes:
            self._show_state(reply, self.view.current_page if self.view else 0)
        else:
            self._state = reply
            self._update_title()
            self._update_edit_actions()

    # Editing

    def _send(self, request: dict) -> None:
        """Send an edit, an undo or redo, or a save; one at a time."""
        if self._engine is None or self.current_file is None or self._busy:
            return
        self._busy = True
        self._update_edit_actions()
        # Ahead of page renders: the pages may be about to change.
        on_reply = functools.partial(self._on_changed, self.current_file, request)
        self._engine.request(request, on_reply, priority=EDIT_PRIORITY)

    def _edit_pages(self, action: str, **arguments: object) -> None:
        if arguments.get("pages") == []:
            return  # nothing selected
        self._send({"op": "edit", "action": action, **arguments})

    def _current_pages(self) -> list[int]:
        """The pages a page action acts on."""
        if self.organize is not None and self._organize_on:
            return self.organize.selected_pages()
        return [self.view.current_page] if self.view is not None else []

    @property
    def _organize_on(self) -> bool:
        return bool(self._actions["organize"].get_state().get_boolean())

    def _on_changed(self, file: Gio.File, request: dict, reply: dict, _payload: bytes) -> None:
        if file is not self.current_file:
            return
        self._busy = False
        if not reply.get("ok"):
            self._close_after_save = False
            message = _edit_error_message(reply.get("error"))
            if request["op"] == "save":
                self._report_save_failure(message)
            else:
                self._toast(message)
            self._update_edit_actions()
            return
        if request["op"] == "save":
            self._on_saved(request, reply)
            return
        if request["op"] == "extract":
            name = GLib.path_get_basename(request["path"])
            self._toast(_("Pages saved as “{name}”").format(name=name))
            self._update_edit_actions()
            return
        if request["op"] == "split":
            folder = GLib.path_get_basename(request["folder"])
            self._toast(_("Split into {count} files in “{folder}”").format(count=len(reply["paths"]), folder=folder))
            self._update_edit_actions()
            return
        select = reply.get("select")
        current = self.view.current_page if self.view is not None else 0
        self._show_state(reply, select[0] if select else min(current, reply["page_count"] - 1))

    def _show_state(self, state: dict, page: int) -> None:
        """Show the document as the engine now has it, at `page`."""
        old = self.view
        engine = self._ensure_engine()
        if old is not None:
            zoom, fit, size = old.zoom, old.fit_mode, (old.get_width(), old.get_height())
        else:
            zoom, fit, size = 1.0, FitMode.WIDTH, self._expected_view_size()
        view = DocumentView(engine, state["pages"], zoom=zoom, fit=fit, page=page, size_hint=size)
        view.connect("current-page-changed", weakly(self._on_current_page_changed))
        view.connect("zoom-changed", weakly(self._on_zoom_changed))
        # A new view starts at its own zoom, fitted to its new pages, before
        # it says so: show that zoom now, not after the next layout.
        self._on_zoom_changed(view)
        self.view = view
        self._state = state
        self._page_sizes = state["pages"]
        self._split.set_content(view)
        if self.sidebar is not None:
            self._split.set_sidebar(None)
            self.sidebar = None
            if self._split.get_show_sidebar():
                self._build_sidebar()
        if self.organize is not None:
            previous = self.organize.selected_pages()
            self._drop_organize()
            count = state["page_count"]
            selected = state.get("select") or [index for index in previous if index < count] or [page]
            self._build_organize(selected)
            self._set_organize(self._organize_on)
        self._page_total.set_label(_("of {count}").format(count=state["page_count"]))
        self._page_entry.set_text(str(view.current_page + 1))
        self._on_zoom_changed(view)
        self._update_title()
        self._update_edit_actions()
        if not self._organize_on:
            view.focus_pages()

    def _update_title(self) -> None:
        if self.current_file is None:
            return
        name = _display_name(self.current_file)
        if self._state.get("modified"):
            # The dot says "not saved", as in other GNOME apps.
            self._title.set_subtitle(f"• {name}")
            self.set_title(_("• {name} – Bluepencil").format(name=name))
        else:
            self._title.set_subtitle(name)
            self.set_title(_("{name} – Bluepencil").format(name=name))

    def _update_edit_actions(self) -> None:
        ready = self.current_file is not None and not self._busy
        enabled = {
            "undo": ready and bool(self._state.get("can_undo")),
            "redo": ready and bool(self._state.get("can_redo")),
            "save": ready and bool(self._state.get("modified")),
            "combine": True,
            "split": ready,
            "compress": ready,
            "save-as": ready,
            "organize": self.current_file is not None,
            **dict.fromkeys(_PAGE_ACTIONS, ready),
        }
        for name, value in enabled.items():
            self._actions[name].set_enabled(value)

    # Saving

    def _on_save(self, *_args: object) -> None:
        if self._state.get("untitled"):
            self._on_save_as()  # a new document needs a place first
        else:
            self._send({"op": "save"})

    def _on_save_as(self, *_args: object) -> None:
        if self.current_file is None:
            return
        dialog = Gtk.FileDialog(title=_("Save As"), modal=True, initial_name=_display_name(self.current_file))
        folder = self.current_file.get_parent()
        if folder is not None:
            dialog.set_initial_folder(folder)
        dialog.save(self, None, weakly(self._on_save_as_chosen))

    def _on_save_as_chosen(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            file = dialog.save_finish(result)
        except GLib.Error as error:
            self._close_after_save = False  # no place chosen: stay open
            if not error.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                self._toast(_("Could not save the file: {reason}").format(reason=error.message))
            return
        if file is not None and file.get_path() is not None:
            self.save_as(file)

    def save_as(self, file: Gio.File) -> None:
        """Save the document to `file` and carry on working there."""
        path = file.get_path()
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self._send({"op": "save", "path": path})

    def _on_saved(self, request: dict, reply: dict) -> None:
        if request.get("path"):
            self.current_file = Gio.File.new_for_path(request["path"])
            self._history.opened(request["path"])
        self._state = {**self._state, **reply}
        self._update_title()
        self._update_edit_actions()
        if self._close_after_save:
            self._discard_confirmed = True
            self.close()

    def _report_save_failure(self, message: str) -> None:
        dialog = Adw.AlertDialog(heading=_("Could Not Save"), body=message)
        dialog.add_response("close", _("_Close"))
        dialog.add_response("save-as", _("Save _As…"))
        dialog.set_response_appearance("save-as", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save-as")
        dialog.set_close_response("close")
        dialog.connect("response", weakly(self._on_save_failure_response))
        dialog.present(self)

    def _on_save_failure_response(self, _dialog: Adw.AlertDialog, response: str) -> None:
        if response == "save-as":
            self._on_save_as()

    def _ask_to_save_before_closing(self) -> None:
        name = _display_name(self.current_file) if self.current_file else ""
        dialog = Adw.AlertDialog(
            heading=_("Save Changes?"),
            body=_("“{name}” has changes that are not saved. If you don’t save, they are lost.").format(name=name),
        )
        dialog.add_response("cancel", _("_Cancel"))
        dialog.add_response("discard", _("_Discard"))
        dialog.add_response("save", _("_Save"))
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")
        dialog.connect("response", weakly(self._on_close_response))
        dialog.present(self)

    def _on_close_response(self, _dialog: Adw.AlertDialog, response: str) -> None:
        if response == "discard":
            self._discard_confirmed = True
            self.close()
        elif response == "save":
            self._close_after_save = True
            self._on_save()

    # Controls

    def _add_actions(self) -> None:
        def add(name, callback, parameter_type=None):
            action = Gio.SimpleAction.new(name, parameter_type)
            # Methods are connected weakly (see ui/weak.py); _view_action's
            # handlers hold the window weakly themselves.
            action.connect("activate", weakly(callback) if inspect.ismethod(callback) else callback)
            self.add_action(action)
            self._actions[name] = action

        add("open", self._on_open_clicked)
        add("combine", self._on_combine_clicked)
        add("zoom-in", self._view_action(DocumentView.zoom_in))
        add("zoom-out", self._view_action(DocumentView.zoom_out))
        add("zoom-fit-width", self._view_action(lambda view: view.fit(FitMode.WIDTH)))
        add("zoom-fit-page", self._view_action(lambda view: view.fit(FitMode.PAGE)))
        add("zoom-percent", self._on_zoom_percent, GLib.VariantType.new("i"))
        add("go-to-page", self._on_go_to_page)
        add("save", self._on_save)
        add("save-as", self._on_save_as)
        add("undo", self._on_undo)
        add("redo", self._on_redo)
        add("rotate-left", self._on_rotate_left)
        add("rotate-right", self._on_rotate_right)
        add("delete-page", self._on_delete_page)
        add("duplicate-pages", self._on_duplicate_pages)
        add("extract-pages", self._on_extract_pages)
        add("insert-blank", self._on_insert_blank)
        add("insert-files", self._on_insert_files)
        add("split", self._on_split)
        add("compress", self._on_compress)
        organize = Gio.SimpleAction.new_stateful("organize", None, GLib.Variant.new_boolean(False))
        organize.connect("change-state", weakly(self._on_toggle_organize))
        self.add_action(organize)
        self._actions["organize"] = organize
        sidebar = Gio.SimpleAction.new_stateful("toggle-sidebar", None, GLib.Variant.new_boolean(False))
        sidebar.connect("change-state", weakly(self._on_toggle_sidebar))
        self.add_action(sidebar)
        self._actions["toggle-sidebar"] = sidebar
        self._set_document_actions(False)
        self._update_edit_actions()

    def _on_undo(self, *_args: object) -> None:
        self._send({"op": "undo"})

    def _on_redo(self, *_args: object) -> None:
        self._send({"op": "redo"})

    def _on_rotate_left(self, *_args: object) -> None:
        self._edit_pages("rotate", pages=self._current_pages(), degrees=-90)

    def _on_rotate_right(self, *_args: object) -> None:
        self._edit_pages("rotate", pages=self._current_pages(), degrees=90)

    def _on_delete_page(self, *_args: object) -> None:
        self._edit_pages("delete", pages=self._current_pages())

    def _on_duplicate_pages(self, *_args: object) -> None:
        self._edit_pages("duplicate", pages=self._current_pages())

    def _on_insert_blank(self, *_args: object) -> None:
        pages = self._current_pages()
        if pages:
            self._edit_pages("insert-blank", at=pages[-1] + 1)

    def _on_insert_files(self, *_args: object) -> None:
        pages = self._current_pages()
        if not pages:
            return
        accepted = Gtk.FileFilter(name=_("PDFs and pictures"))
        accepted.add_mime_type("application/pdf")
        accepted.add_pixbuf_formats()
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(accepted)
        dialog = Gtk.FileDialog(title=_("Insert Pages or Pictures"), modal=True, filters=filters)
        dialog.open_multiple(self, None, weakly(self._on_insert_files_chosen), pages[-1] + 1)

    def _on_insert_files_chosen(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult, at: int) -> None:
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return  # closed without choosing
        paths = [file.get_path() for file in files if file.get_path() is not None]
        if paths:
            self.insert_files(paths, at)

    def insert_files(self, paths: list[str], at: int) -> None:
        """Insert PDFs and pictures before page `at`, as one step."""
        self._send({"op": "edit", "action": "insert-files", "paths": paths, "at": at})

    def _on_extract_pages(self, *_args: object) -> None:
        pages = self._current_pages()
        if not pages or self.current_file is None:
            return
        stem = _display_name(self.current_file).removesuffix(".pdf")
        span = str(pages[0] + 1) if len(pages) == 1 else f"{pages[0] + 1}-{pages[-1] + 1}"
        name = _("{name}, pages {span}.pdf").format(name=stem, span=span)
        dialog = Gtk.FileDialog(title=_("Extract Pages"), modal=True, initial_name=name)
        folder = self.current_file.get_parent()
        if folder is not None:
            dialog.set_initial_folder(folder)
        dialog.save(self, None, weakly(self._on_extract_chosen), pages)

    def _on_extract_chosen(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult, pages: list[int]) -> None:
        try:
            file = dialog.save_finish(result)
        except GLib.Error:
            return
        if file is not None and file.get_path() is not None:
            self.extract_pages(pages, file.get_path())

    def extract_pages(self, pages: list[int], path: str) -> None:
        """Write these pages to a new PDF at `path`; the document is unchanged."""
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self._send({"op": "extract", "pages": pages, "path": path})

    def _on_split(self, *_args: object) -> None:
        if self.view is None:
            return
        dialog = SplitDialog(self.view.page_count)
        dialog.connect("split-requested", weakly(self._on_split_requested))
        dialog.present(self)

    def _on_split_requested(self, _dialog: SplitDialog, groups: list[list[int]]) -> None:
        chooser = Gtk.FileDialog(title=_("Choose a Folder for the New Files"), modal=True)
        folder = self.current_file.get_parent() if self.current_file is not None else None
        if folder is not None:
            chooser.set_initial_folder(folder)
        chooser.select_folder(self, None, weakly(self._on_split_folder_chosen), groups)

    def _on_split_folder_chosen(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult, groups: list) -> None:
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        if folder is not None and folder.get_path() is not None:
            self.split_into(groups, folder.get_path())

    def split_into(self, groups: list[list[int]], folder: str) -> None:
        """Write each group of pages to its own new PDF in `folder`."""
        if self.current_file is None:
            return
        stem = _display_name(self.current_file).removesuffix(".pdf")
        self._send({"op": "split", "groups": groups, "folder": folder, "stem": stem})

    # Compress

    def _on_compress(self, *_args: object) -> None:
        if self.current_file is None:
            return
        # What is on screen, unsaved changes included.
        history = self._state.get("history")
        if self._state.get("modified") and history:
            source = history["files"][history["position"]]
        else:
            source = self.current_file.get_path()
        on_disk = Path(self.current_file.get_path())
        size = (on_disk if on_disk.exists() else Path(source)).stat().st_size
        dialog = CompressDialog(source, self._password, size, jobs_root())
        dialog.connect("save-requested", weakly(self._on_compressed_save_requested))
        self.compress_dialog = dialog
        dialog.present(self)

    def _on_compressed_save_requested(self, dialog: CompressDialog, _result: str) -> None:
        if self.current_file is None:
            return
        stem = _display_name(self.current_file).removesuffix(".pdf")
        chooser = Gtk.FileDialog(
            title=_("Save a Smaller Copy"), modal=True, initial_name=_("{name} (smaller).pdf").format(name=stem)
        )
        folder = self.current_file.get_parent()
        if folder is not None and folder.query_exists(None):
            chooser.set_initial_folder(folder)
        chooser.save(self, None, weakly(self._on_compressed_target_chosen), dialog)

    def _on_compressed_target_chosen(
        self, chooser: Gtk.FileDialog, result: Gio.AsyncResult, dialog: CompressDialog
    ) -> None:
        try:
            file = chooser.save_finish(result)
        except GLib.Error:
            return
        if file is not None and file.get_path() is not None:
            self.save_compressed_copy(dialog, file.get_path())

    def save_compressed_copy(self, dialog: CompressDialog, path: str) -> None:
        """Put the smaller copy at `path` and close the dialog."""
        if dialog.result_path is None:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        if self.current_file is not None and Path(path) == Path(self.current_file.get_path()):
            # The open document is never replaced by a compressed copy.
            self._toast(_("Choose another name: compressing keeps the original as it is."))
            return
        try:
            shutil.move(dialog.result_path, path)
        except OSError as error:
            self._toast(_("Could not save the smaller copy: {reason}").format(reason=error.strerror))
            return
        dialog.result_path = None
        dialog.close()
        self._toast(_("Saved a smaller copy as “{name}”").format(name=Path(path).name))

    # Organize mode

    def _on_toggle_organize(self, action: Gio.SimpleAction, value: GLib.Variant) -> None:
        action.set_state(value)
        self._set_organize(value.get_boolean())

    def _set_organize(self, on: bool) -> None:
        if on and self.view is not None and self.organize is None:
            self._build_organize(self._current_pages())
        organize = self.organize
        if organize is None:
            return
        organize.set_open(on)
        self._bottom_bar.set_visible(not on)
        self._organize_bar.set_visible(on)
        if on:
            self._stack.set_visible_child(organize)
            organize.reveal_selected()
            organize.focus_grid()
        else:
            self._stack.set_visible_child(self._split)
            pages = organize.selected_pages()
            if pages and self.view is not None:
                self.view.go_to_page(pages[0])
                self.view.focus_pages()

    def _build_organize(self, selected: list[int]) -> None:
        engine = self._ensure_engine()
        organize = OrganizeView(engine, self._page_sizes)
        organize.connect("edit-requested", weakly(self._on_organize_edit))
        organize.connect("insert-requested", weakly(self._on_organize_insert))
        organize.connect("page-chosen", weakly(self._on_organize_page_chosen))
        organize.select_pages(selected)
        self.organize = organize
        self._stack.add_child(organize)

    def _drop_organize(self) -> None:
        if self.organize is not None:
            self._stack.remove(self.organize)
            self.organize = None

    def _on_organize_edit(self, _organize: OrganizeView, request: dict) -> None:
        self._send({"op": "edit", **request})

    def _on_organize_insert(self, _organize: OrganizeView, paths: list[str], at: int) -> None:
        self.insert_files(paths, at)

    def _on_organize_page_chosen(self, _organize: OrganizeView, index: int, activated: bool) -> None:
        if activated:  # Enter or a double click: read from that page
            self._actions["organize"].change_state(GLib.Variant.new_boolean(False))
            if self.view is not None:
                self.view.go_to_page(index)

    def _view_action(self, method: Callable[[DocumentView], object]) -> Callable[..., None]:
        """An action handler that calls `method` on the page view, if any."""
        window = weakref.ref(self)

        def activate(*_args: object) -> None:
            view = getattr(window(), "view", None)
            if view is not None:
                method(view)

        return activate

    def _set_document_actions(self, enabled: bool) -> None:
        for name in _DOCUMENT_ACTIONS:
            self._actions[name].set_enabled(enabled)

    def _build_status_page(self) -> Adw.StatusPage:
        """The start page, which also shows "Opening…" and errors."""
        self._open_button = Gtk.Button(label=_("Open PDF…"), action_name="win.open")
        self._open_button.add_css_class("pill")
        self._open_button.add_css_class("suggested-action")
        self._combine_button = Gtk.Button(
            label=_("Combine Files…"),
            action_name="win.combine",
            tooltip_text=_("Make one PDF from several PDFs and pictures"),
        )
        self._combine_button.add_css_class("pill")
        # Both buttons fill the centred box, so both are as wide as the wider
        # one: stacked buttons line up, and colour alone says which matters.
        buttons = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        buttons.append(self._open_button)
        buttons.append(self._combine_button)
        start = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=36)
        start.append(buttons)
        start.append(self._build_recent_files())
        return Adw.StatusPage(vexpand=True, child=Adw.Clamp(maximum_size=520, child=start))

    def _build_header(self) -> Adw.HeaderBar:
        header = Adw.HeaderBar(title_widget=self._title)
        header.pack_start(
            Gtk.ToggleButton(
                icon_name="sidebar-show-symbolic",
                action_name="win.toggle-sidebar",
                tooltip_text=_("Page Thumbnails (F9)"),
            )
        )
        header.pack_start(
            Gtk.ToggleButton(
                icon_name="view-grid-symbolic",
                action_name="win.organize",
                tooltip_text=_("Organize Pages (Ctrl+G)"),
            )
        )
        self._open_header_button = Gtk.Button(
            label=_("Open"), action_name="win.open", tooltip_text=_("Open a PDF (Ctrl+O)")
        )
        header.pack_start(self._open_header_button)
        header.pack_end(self._build_menu_button())
        # In narrow windows a smaller Save button takes this one's place.
        self._save_button = Gtk.Button(label=_("Save"), action_name="win.save", tooltip_text=_("Save (Ctrl+S)"))
        self._save_button.add_css_class("suggested-action")
        self._save_icon_button = Gtk.Button(
            icon_name="document-save-symbolic", action_name="win.save", tooltip_text=_("Save (Ctrl+S)"), visible=False
        )
        self._save_icon_button.add_css_class("suggested-action")
        header.pack_end(self._save_button)
        header.pack_end(self._save_icon_button)
        return header

    def _build_menu_button(self) -> Gtk.MenuButton:
        files = Gio.Menu()
        files.append(_("Open…"), "win.open")
        files.append(_("Save As…"), "win.save-as")
        edits = Gio.Menu()
        edits.append(_("Undo"), "win.undo")
        edits.append(_("Redo"), "win.redo")
        page = Gio.Menu()
        page.append(_("Organize Pages"), "win.organize")
        page.append(_("Rotate Left"), "win.rotate-left")
        page.append(_("Rotate Right"), "win.rotate-right")
        page.append(_("Duplicate"), "win.duplicate-pages")
        page.append(_("Delete"), "win.delete-page")
        page.append(_("Insert Blank Page"), "win.insert-blank")
        page.append(_("Insert Pages or Pictures…"), "win.insert-files")
        page.append(_("Extract…"), "win.extract-pages")
        page.append(_("Split…"), "win.split")
        tools = Gio.Menu()
        tools.append(_("Compress…"), "win.compress")
        app = Gio.Menu()
        app.append(_("About {name}").format(name=APP_NAME), "app.about")
        app.append(_("Quit"), "app.quit")
        menu = Gio.Menu()
        menu.append_section(None, files)
        menu.append_section(None, edits)
        menu.append_section(_("Pages"), page)
        menu.append_section(_("Tools"), tools)
        menu.append_section(None, app)
        return Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text=_("Main Menu"))

    def _build_organize_bar(self) -> Gtk.ActionBar:
        """Tools for the selected pages in Organize mode."""
        bar = Gtk.ActionBar()

        def button(icon: str, action: str, tooltip: str) -> Gtk.Button:
            return Gtk.Button(icon_name=icon, action_name=f"win.{action}", tooltip_text=tooltip)

        tools = Gtk.Box(spacing=6)
        tools.append(button("object-rotate-left-symbolic", "rotate-left", _("Rotate Left (Ctrl+[)")))
        tools.append(button("object-rotate-right-symbolic", "rotate-right", _("Rotate Right (Ctrl+])")))
        tools.append(button("edit-copy-symbolic", "duplicate-pages", _("Duplicate")))
        tools.append(button("user-trash-symbolic", "delete-page", _("Delete (Delete)")))
        insert = Gio.Menu()
        insert.append(_("Blank Page"), "win.insert-blank")
        insert.append(_("Pages or Pictures From Files…"), "win.insert-files")
        tools.append(Gtk.MenuButton(icon_name="list-add-symbolic", menu_model=insert, tooltip_text=_("Insert")))
        self._extract_button = Gtk.Button(
            label=_("Extract…"),
            action_name="win.extract-pages",
            tooltip_text=_("Save the selected pages as a new PDF"),
        )
        self._split_button = Gtk.Button(
            label=_("Split…"),
            action_name="win.split",
            tooltip_text=_("Cut the document into several new PDFs"),
        )
        # In narrow windows the two labelled buttons fold into this menu.
        more = Gio.Menu()
        more.append(_("Extract…"), "win.extract-pages")
        more.append(_("Split…"), "win.split")
        self._more_pages_button = Gtk.MenuButton(
            icon_name="view-more-symbolic", menu_model=more, tooltip_text=_("More"), visible=False
        )
        for widget in (self._extract_button, self._split_button, self._more_pages_button):
            tools.append(widget)
        bar.pack_start(tools)

        history = Gtk.Box()
        history.add_css_class("linked")
        history.append(button("edit-undo-symbolic", "undo", _("Undo (Ctrl+Z)")))
        history.append(button("edit-redo-symbolic", "redo", _("Redo (Ctrl+Shift+Z)")))
        bar.pack_end(history)
        return bar

    def _build_bottom_bar(self) -> Gtk.ActionBar:
        bar = Gtk.ActionBar()

        self._page_entry = Gtk.Entry(
            width_chars=4, max_width_chars=6, xalign=1.0, input_purpose=Gtk.InputPurpose.DIGITS
        )
        self._page_entry.update_property([Gtk.AccessibleProperty.LABEL], [_("Page number")])
        self._page_entry.connect("activate", weakly(self._on_page_entry_activate))
        self._page_total = Gtk.Label()
        pages = Gtk.Box(spacing=6)
        pages.append(self._page_entry)
        pages.append(self._page_total)
        bar.pack_start(pages)

        fit = Gio.Menu()
        fit.append(_("Fit Width"), "win.zoom-fit-width")
        fit.append(_("Fit Page"), "win.zoom-fit-page")
        presets = Gio.Menu()
        for percent in ZOOM_PRESETS:
            item = Gio.MenuItem.new(_("{percent}%").format(percent=percent), None)
            item.set_action_and_target_value("win.zoom-percent", GLib.Variant.new_int32(percent))
            presets.append_item(item)
        menu = Gio.Menu()
        menu.append_section(None, fit)
        menu.append_section(None, presets)
        self._zoom_button = Gtk.MenuButton(label="100%", menu_model=menu, tooltip_text=_("Zoom"))

        zoom = Gtk.Box()
        zoom.add_css_class("linked")
        zoom.append(Gtk.Button(icon_name="zoom-out-symbolic", action_name="win.zoom-out", tooltip_text=_("Zoom Out")))
        zoom.append(self._zoom_button)
        zoom.append(Gtk.Button(icon_name="zoom-in-symbolic", action_name="win.zoom-in", tooltip_text=_("Zoom In")))
        bar.pack_end(zoom)
        return bar

    def _toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=5))

    def _on_go_to_page(self, *_args: object) -> None:
        self._page_entry.grab_focus()

    def _on_page_entry_activate(self, entry: Gtk.Entry) -> None:
        if self.view is None:
            return
        try:
            number = int(entry.get_text().strip())
        except ValueError:
            number = self.view.current_page + 1
        number = min(max(number, 1), self.view.page_count)
        self.view.go_to_page(number - 1)
        entry.set_text(str(number))
        self.view.focus_pages()

    def _on_current_page_changed(self, _view: DocumentView, index: int) -> None:
        focus = self.get_focus()
        if focus is None or not focus.is_ancestor(self._page_entry):
            self._page_entry.set_text(str(index + 1))
        if self.sidebar is not None:
            self.sidebar.show_page(index)
        self._remember_position()

    def _on_page_chosen(self, _sidebar: ThumbnailSidebar, index: int, activated: bool) -> None:
        if self.view is None:
            return
        self.view.go_to_page(index)
        if activated:  # Enter or a double click: carry on reading there
            self.view.focus_pages()

    def _on_toggle_sidebar(self, action: Gio.SimpleAction, value: GLib.Variant) -> None:
        action.set_state(value)
        self._split.set_show_sidebar(value.get_boolean())

    def _on_sidebar_shown(self, split: Adw.OverlaySplitView, _pspec: object) -> None:
        # Also covers the sidebar closing itself, e.g. by a click beside it
        # in a narrow window.
        shown = split.get_show_sidebar()
        self._actions["toggle-sidebar"].set_state(GLib.Variant.new_boolean(shown))
        if shown:
            self._build_sidebar()
        if self.sidebar is not None:
            self.sidebar.set_open(shown)
            if shown:
                GLib.idle_add(self._reveal_current_thumbnail)

    def _reveal_current_thumbnail(self) -> bool:
        if self.sidebar is not None:
            self.sidebar.reveal_selected()
        return GLib.SOURCE_REMOVE

    def _on_zoom_changed(self, view: DocumentView) -> None:
        self._zoom_button.set_label(_("{percent}%").format(percent=round(view.zoom * 100)))
        self._remember_position()

    def _on_zoom_percent(self, _action: Gio.SimpleAction, parameter: GLib.Variant) -> None:
        if self.view is not None:
            self.view.set_zoom(parameter.get_int32() / 100)

    def _on_drop(self, _target: Gtk.DropTarget, value: object, _x: float, _y: float) -> bool:
        """One file opens; several go to the Combine list."""
        if not isinstance(value, Gdk.FileList):
            return False
        files = value.get_files()
        if len(files) == 1 and self.combine_dialog is None:
            self.get_application().open_file(files[0], self)
            return True
        paths = [path for file in files if (path := file.get_path()) is not None]
        if paths:
            self.show_combine_list(paths)
        return bool(paths)

    def _on_close_request(self, _window: Gtk.Window) -> bool:
        if self._state.get("modified") and not self._discard_confirmed:
            if not self._busy:
                self._ask_to_save_before_closing()
            return True  # not yet: the user decides first
        self.shutdown()
        return False

    def _on_open_clicked(self, *_args: object) -> None:
        pdf_filter = Gtk.FileFilter(name=_("PDF documents"))
        pdf_filter.add_mime_type("application/pdf")
        pdf_filter.add_suffix("pdf")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(pdf_filter)
        dialog = Gtk.FileDialog(title=_("Open PDF"), modal=True, filters=filters, default_filter=pdf_filter)
        dialog.open(self, None, self._on_file_chosen)

    def _on_file_chosen(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            file = dialog.open_finish(result)
        except GLib.Error as error:
            # Closing the dialog without choosing a file is not an error.
            if not error.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                self._toast(_("Could not open the file: {reason}").format(reason=error.message))
            return
        if file is not None:
            self.get_application().open_file(file, self)

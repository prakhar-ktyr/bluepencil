# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The main window: header bar, the open document, and the bar below it."""

import functools
import inspect
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
from .engine_client import EngineClient  # noqa: E402
from .history import History  # noqa: E402
from .i18n import _  # noqa: E402
from .ui.document_view import DocumentView, FitMode  # noqa: E402
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

#: Actions that change the document, or save it.
_EDIT_ACTIONS = ("undo", "redo", "save", "save-as", "rotate-left", "rotate-right", "delete-page")

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
    }
    return messages.get(code or "", _("Something went wrong while opening the file."))


def _edit_error_message(code: str | None) -> str:
    messages = {
        "no-pages-left": _("A document needs at least one page."),
        "no-permission": _("You don’t have permission to save in this folder. Use Save As to save a copy elsewhere."),
        "read-only": _("This location is read-only. Use Save As to save a copy elsewhere."),
        "disk-full": _("The disk is full. Free some space, or save the file somewhere else."),
        "check-failed": _("The saved file could not be read back, so the original was kept as it was."),
        "write-failed": _("The file could not be written. The original was kept as it was."),
    }
    return messages.get(code or "", _("That did not work, and nothing was changed."))


def _display_name(file: Gio.File) -> str:
    return file.get_basename() or _("Untitled")


def _display_folder(path: str) -> str:
    """The folder of `path`, with the home folder shown as ~."""
    folder = Path(path).parent
    home = Path.home()
    if folder == home:
        return "~"
    if folder.is_relative_to(home):
        return str(Path("~") / folder.relative_to(home))
    return str(folder)


class BluepencilWindow(Adw.ApplicationWindow):
    __gtype_name__ = "BluepencilWindow"

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.set_title(APP_NAME)
        self.set_default_size(1000, 760)

        #: The file on show, once it has opened.
        self.current_file: Gio.File | None = None
        #: The page view and the thumbnails, while a file is on show.
        self.view: DocumentView | None = None
        self.sidebar: ThumbnailSidebar | None = None
        self._engine: EngineClient | None = None
        self._loading: Gio.File | None = None
        self._loading_password: str | None = None
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
        self._actions: dict[str, Gio.SimpleAction] = {}
        #: Rows of the recent files list, with the path each one opens.
        self._recent_rows: list[tuple[str, Adw.ActionRow]] = []
        self._history_handler = 0
        self._add_actions()

        self._title = Adw.WindowTitle(title=APP_NAME)
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
        self.set_content(self._toolbar)
        self._show_start()

        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 600sp"))
        narrow.add_setter(self._split, "collapsed", True)
        self.add_breakpoint(narrow)
        self.set_size_request(360, 400)  # windows with breakpoints need a minimum size

        # Start the PDF engine while the user picks a file: loading the PDF
        # library takes about a third of a second.
        GLib.idle_add(self._start_engine_early)

        drop = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
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
        self._remember_position()
        if self._history_handler:
            self._history.disconnect(self._history_handler)
            self._history_handler = 0
        if self._engine is not None:
            self._engine.close()
            self._engine = None

    @property
    def _history(self) -> History:
        return self.get_application().history

    # Opening

    def _load(self, file: Gio.File, password: str | None) -> None:
        self._loading = file
        self._loading_password = password
        engine = self._ensure_engine()
        engine.request(
            {"op": "open", "path": file.get_path(), "password": password},
            functools.partial(self._on_opened, file, password),
            key=("open",),
            priority=OPEN_PRIORITY,
        )
        GLib.timeout_add(LOADING_DELAY_MS, self._show_loading, file)

    def _start_engine_early(self) -> bool:
        if self.get_application() is not None:  # not closed in the meantime
            self._ensure_engine()
        return GLib.SOURCE_REMOVE

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
        self._history.opened(path)
        view.connect("current-page-changed", weakly(self._on_current_page_changed))
        view.connect("zoom-changed", weakly(self._on_zoom_changed))
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
                subtitle=_display_folder(entry.path),
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
            self._show_error(file, "engine-failed")
            return
        self._toast(_("The PDF engine stopped unexpectedly and was restarted"))
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
        self._send({"op": "edit", "action": action, **arguments})

    def _current_pages(self) -> list[int]:
        return [self.view.current_page] if self.view is not None else []

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
        self.view = view
        self._state = state
        self._page_sizes = state["pages"]
        self._split.set_content(view)
        if self.sidebar is not None:
            self._split.set_sidebar(None)
            self.sidebar = None
            if self._split.get_show_sidebar():
                self._build_sidebar()
        self._page_total.set_label(_("of {count}").format(count=state["page_count"]))
        self._page_entry.set_text(str(view.current_page + 1))
        self._on_zoom_changed(view)
        self._update_title()
        self._update_edit_actions()
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
            "save-as": ready,
            "rotate-left": ready,
            "rotate-right": ready,
            "delete-page": ready,
        }
        for name, value in enabled.items():
            self._actions[name].set_enabled(value)

    # Saving

    def _on_save(self, *_args: object) -> None:
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
        self._open_button = Gtk.Button(label=_("Open PDF…"), action_name="win.open", halign=Gtk.Align.CENTER)
        self._open_button.add_css_class("pill")
        self._open_button.add_css_class("suggested-action")
        start = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=36)
        start.append(self._open_button)
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
        header.pack_start(Gtk.Button(label=_("Open"), action_name="win.open", tooltip_text=_("Open a PDF")))
        header.pack_end(self._build_menu_button())
        self._save_button = Gtk.Button(label=_("Save"), action_name="win.save", tooltip_text=_("Save (Ctrl+S)"))
        self._save_button.add_css_class("suggested-action")
        header.pack_end(self._save_button)
        return header

    def _build_menu_button(self) -> Gtk.MenuButton:
        files = Gio.Menu()
        files.append(_("Save As…"), "win.save-as")
        edits = Gio.Menu()
        edits.append(_("Undo"), "win.undo")
        edits.append(_("Redo"), "win.redo")
        page = Gio.Menu()
        page.append(_("Rotate Page Left"), "win.rotate-left")
        page.append(_("Rotate Page Right"), "win.rotate-right")
        page.append(_("Delete Page"), "win.delete-page")
        app = Gio.Menu()
        app.append(_("About {name}").format(name=APP_NAME), "app.about")
        app.append(_("Quit"), "app.quit")
        menu = Gio.Menu()
        for section in (files, edits, page, app):
            menu.append_section(None, section)
        return Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text=_("Main Menu"))

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
        if not isinstance(value, Gio.File):
            return False
        self.get_application().open_file(value, self)
        return True

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

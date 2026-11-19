# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Combine list: put files in order, from any folders, before combining.

Each file shows its place in the order, its first page and its page count.
Files are dragged into place, or moved from their menus, which also show the
shortcuts, so that nothing depends on dragging: the reorderable lists of
GNOME Settings work the same way. The file the shortcuts move, the one
clicked last, is tinted. Add Files… can be used again and again, in any
folder, and files can be dropped on the list from the Files app.

Files are read by an engine process of the list's own (plan, D1), one at a
time: a file that crashes the PDF library is then known, and it cannot take
an open document down with it. Files that cannot be combined say why, and
locked ones can be unlocked here.
"""

import functools
from collections.abc import Sequence
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Graphene, Gtk  # noqa: E402

from ..engine_client import EngineClient  # noqa: E402
from ..i18n import _, ngettext  # noqa: E402
from .names import display_folder  # noqa: E402
from .thumbnails import ThumbnailSheet, thumbnail_size  # noqa: E402
from .weak import weakly  # noqa: E402

#: Largest first-page picture, in logical pixels. The engine draws it twice
#: as big, so that it is sharp on high-resolution screens too.
PREVIEW_SIZE = 48

#: The moves of a file's menu, by action name, and their keys with Alt.
MOVE_KEYS = {
    "move-up": (Gdk.KEY_Up, Gdk.KEY_KP_Up),
    "move-down": (Gdk.KEY_Down, Gdk.KEY_KP_Down),
    "move-to-top": (Gdk.KEY_Home, Gdk.KEY_KP_Home),
    "move-to-bottom": (Gdk.KEY_End, Gdk.KEY_KP_End),
}


def _move_menu() -> Gio.Menu:
    """Each move, with its shortcut beside it: the menu teaches the keys."""
    labels = {
        "move-up": _("Move Up"),
        "move-down": _("Move Down"),
        "move-to-top": _("Move to Top"),
        "move-to-bottom": _("Move to Bottom"),
    }
    menu = Gio.Menu()
    for names in (("move-up", "move-down"), ("move-to-top", "move-to-bottom")):
        section = Gio.Menu()
        for name in names:
            item = Gio.MenuItem.new(labels[name], f"row.{name}")
            accel = Gtk.accelerator_name(MOVE_KEYS[name][0], Gdk.ModifierType.ALT_MASK)
            item.set_attribute_value("accel", GLib.Variant.new_string(accel))
            section.append_item(item)
        menu.append_section(None, section)
    return menu


def files_filter() -> Gtk.FileFilter:
    """What the file chooser offers: PDFs and pictures."""
    accepted = Gtk.FileFilter(name=_("PDFs and pictures"))
    accepted.add_mime_type("application/pdf")
    accepted.add_pixbuf_formats()
    return accepted


def _problem_text(code: str) -> str:
    return {
        "needs-password": _("Locked with a password"),
        "wrong-password": _("That password is not correct"),
        "not-found": _("This file doesn’t exist any more"),
        "no-permission": _("You don’t have permission to read this file"),
        "unsupported-file": _("Not a PDF or a picture, or damaged"),
        "engine-failed": _("Reading this file stopped Bluepencil’s PDF engine"),
    }.get(code, _("This file can’t be read"))


def announce(widget: Gtk.Widget, message: str) -> None:
    """Have screen readers say `message`, once they are free.

    Not through GTK's stand-in for a missing accessibility bus (as on a
    server, or with GTK_A11Y=test): it has no way to announce, and GTK 4.14
    to 4.18 at least crash when asked to.
    """
    context = widget.get_at_context()
    if context is not None and context.__gtype__.name != "GtkTestATContext":
        widget.announce(message, Gtk.AccessibleAnnouncementPriority.MEDIUM)


class FileRow(Adw.ActionRow):
    """One file of the list, with what the engine found out about it.

    Emits move-requested with the name of a move of MOVE_KEYS, chosen from
    its menu.
    """

    __gtype_name__ = "BluepencilCombineRow"
    __gsignals__: dict[str, tuple] = {
        "move-requested": (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }

    def __init__(self, path: str) -> None:
        name = Path(path).name
        # use_markup off: a file name is shown as it is, "&" and all.
        super().__init__(title=name, use_markup=False, title_lines=1, subtitle_lines=1, tooltip_text=path)
        self.path = path
        #: Unlocks the file, once the user has given it.
        self.password: str | None = None
        #: Pages it adds, once read.
        self.pages: int | None = None
        #: Why it cannot be combined, if it cannot.
        self.problem: str | None = None

        handle = Gtk.Image(icon_name="list-drag-handle-symbolic")
        handle.add_css_class("dim-label")
        self.sheet = ThumbnailSheet(PREVIEW_SIZE)
        self.sheet.set_valign(Gtk.Align.CENTER)
        self.icon = Gtk.Image(pixel_size=24)
        self.icon.add_css_class("dim-label")
        self._preview = Gtk.Stack()
        self._preview.add_named(self.sheet, "sheet")
        self._preview.add_named(self.icon, "icon")
        #: Its place in the order, on the corner of the picture.
        self.number = Gtk.Label(halign=Gtk.Align.START, valign=Gtk.Align.START)
        for style in ("bp-order-number", "caption", "numeric"):
            self.number.add_css_class(style)
        preview = Gtk.Overlay(
            child=self._preview,
            width_request=PREVIEW_SIZE,
            height_request=PREVIEW_SIZE,
            valign=Gtk.Align.CENTER,
            margin_top=6,
            margin_bottom=6,
        )
        preview.add_overlay(self.number)
        # Each prefix goes before the ones added earlier: the handle comes first.
        self.add_prefix(preview)
        self.add_prefix(handle)

        self.warning = Gtk.Image(icon_name="dialog-warning-symbolic", visible=False)
        self.warning.add_css_class("error")
        self.unlock_button = Gtk.Button(
            label=_("_Unlock…"), use_underline=True, valign=Gtk.Align.CENTER, visible=False
        )
        self.unlock_button.update_property([Gtk.AccessibleProperty.LABEL], [_("Unlock “{name}”").format(name=name)])
        self.remove_button = Gtk.Button(icon_name="window-close-symbolic", valign=Gtk.Align.CENTER)
        self.remove_button.set_tooltip_text(_("Remove"))
        self.remove_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Remove “{name}” from the list").format(name=name)]
        )
        self.remove_button.add_css_class("flat")

        self._moves = Gio.SimpleActionGroup()
        for move in MOVE_KEYS:
            action = Gio.SimpleAction(name=move)
            action.connect("activate", weakly(self._on_move_activated))
            self._moves.add_action(action)
        self.insert_action_group("row", self._moves)
        self.menu_button = Gtk.MenuButton(
            icon_name="view-more-symbolic", menu_model=_move_menu(), valign=Gtk.Align.CENTER, tooltip_text=_("Move")
        )
        self.menu_button.update_property([Gtk.AccessibleProperty.LABEL], [_("Move “{name}”").format(name=name)])
        self.menu_button.add_css_class("flat")
        self.add_suffix(self.warning)
        self.add_suffix(self.unlock_button)
        self.add_suffix(self.menu_button)
        self.add_suffix(self.remove_button)

        # The whole row can be dragged, so the pointer is a hand all over it;
        # its buttons are clicked, so they keep the arrow.
        self.set_cursor_from_name("grab")
        for button in (self.unlock_button, self.menu_button, self.remove_button):
            button.set_cursor_from_name("default")
        self.show_reading()

    @property
    def needs_reading(self) -> bool:
        return self.pages is None and self.problem is None

    def set_place(self, number: int, count: int) -> None:
        """Show the file's place in the order, and offer only the moves that
        go somewhere."""
        self.number.set_label(str(number))
        for move in MOVE_KEYS:
            action = self._moves.lookup_action(move)
            if isinstance(action, Gio.SimpleAction):
                action.set_enabled(number > 1 if move in ("move-up", "move-to-top") else number < count)
        self.menu_button.set_sensitive(count > 1)

    def _on_move_activated(self, action: Gio.SimpleAction, _parameter: GLib.Variant | None) -> None:
        self.emit("move-requested", action.get_name())

    def show_reading(self) -> None:
        self.pages, self.problem = None, None
        self.sheet.show(thumbnail_size(595, 842, PREVIEW_SIZE, PREVIEW_SIZE), None)
        self._preview.set_visible_child(self.sheet)
        self._show_details(_("Reading…"))

    def show_contents(self, info: dict, pixels: bytes) -> None:
        self.pages, self.problem = int(info["pages"]), None
        texture = Gdk.MemoryTexture.new(
            info["width"], info["height"], Gdk.MemoryFormat.R8G8B8, GLib.Bytes.new(pixels), info["stride"]
        )
        self.sheet.show(thumbnail_size(info["width"], info["height"], PREVIEW_SIZE, PREVIEW_SIZE), texture)
        self._preview.set_visible_child(self.sheet)
        if info.get("kind") == "picture":
            self._show_details(_("Picture"))
        else:
            self._show_details(ngettext("{count} page", "{count} pages", self.pages).format(count=self.pages))

    def show_problem(self, code: str) -> None:
        self.pages, self.problem = None, code
        locked = code in ("needs-password", "wrong-password")
        self.icon.set_from_icon_name("system-lock-screen-symbolic" if locked else "dialog-warning-symbolic")
        self._preview.set_visible_child(self.icon)
        self._show_details(_problem_text(code))

    def _show_details(self, status: str) -> None:
        self.set_subtitle(_("{status} · {folder}").format(status=status, folder=display_folder(self.path)))
        self.warning.set_visible(self.problem is not None)
        self.warning.set_tooltip_text(_problem_text(self.problem) if self.problem else None)
        self.unlock_button.set_visible(self.problem in ("needs-password", "wrong-password"))


class CombineDialog(Adw.Dialog):
    """Emits combine-requested with the paths in order, and the passwords that
    unlock locked files, by path."""

    __gtype_name__ = "BluepencilCombineDialog"
    __gsignals__: dict[str, tuple] = {
        "combine-requested": (GObject.SignalFlags.RUN_LAST, None, (object, object)),
    }

    def __init__(self, paths: Sequence[str]) -> None:
        super().__init__(title=_("Combine Files"), content_width=520)
        self._engine = EngineClient()
        self._engine.connect("died", weakly(self._on_engine_died))
        #: The file the engine is reading.
        self._reading: FileRow | None = None
        #: Combine was pressed while files were still being read.
        self._combine_when_read = False
        self._closed = False
        # Tells this list's own rows apart from anything else dragged.
        self._drag_tag = f"bluepencil-combine-{id(self)}:"
        self._drag_hotspot = (0, 0)
        #: The locked file whose password is being asked for, and the entry.
        self._unlocking: tuple[FileRow, Gtk.PasswordEntry] | None = None

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(self._build_files_page(), "files")
        self.stack.add_named(self._build_empty_page(), "empty")
        drop = Gtk.DropTarget(actions=Gdk.DragAction.MOVE | Gdk.DragAction.COPY)
        drop.set_gtypes([GObject.TYPE_STRING, Gdk.FileList])
        drop.connect("motion", weakly(self._on_drop_motion))
        drop.connect("leave", weakly(self._on_drop_leave))
        drop.connect("drop", weakly(self._on_drop))
        self.stack.add_controller(drop)

        self.add_button = Gtk.Button(
            child=Adw.ButtonContent(icon_name="list-add-symbolic", label=_("_Add Files…"), use_underline=True),
            tooltip_text=_("Add PDFs and pictures from any folder"),
        )
        self.add_button.connect("clicked", weakly(self._on_add_clicked))
        header = Adw.HeaderBar()
        header.pack_start(self.add_button)

        view = Adw.ToolbarView(content=self.stack)
        view.add_top_bar(header)
        view.add_bottom_bar(self._build_bottom_bar())
        self.set_child(view)
        self.connect("closed", weakly(self._on_closed))
        self.add_files(paths)

    def _build_files_page(self) -> Gtk.Widget:
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("boxed-list")
        self.list.add_css_class("bp-combine-list")  # tints the focused file
        self.list.update_property([Gtk.AccessibleProperty.LABEL], [_("Files to combine, in order")])
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", weakly(self._on_key_pressed))
        self.list.add_controller(keys)
        hint = Gtk.Label(
            label=_("Drag files to change the order. Add more from any folder, or drop them here."),
            wrap=True,
            xalign=0,
        )
        hint.add_css_class("dim-label")
        files = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=6, margin_bottom=12)
        files.append(hint)
        files.append(self.list)
        return Gtk.ScrolledWindow(
            child=Adw.Clamp(child=files, maximum_size=560, margin_start=12, margin_end=12),
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True,
            vexpand=True,
        )

    def _build_empty_page(self) -> Gtk.Widget:
        add = Gtk.Button(label=_("_Add Files…"), use_underline=True, halign=Gtk.Align.CENTER)
        add.add_css_class("pill")
        add.connect("clicked", weakly(self._on_add_clicked))
        empty = Adw.StatusPage(
            icon_name="folder-documents-symbolic",
            title=_("No Files"),
            description=_("Add PDFs and pictures from any folder, or drop them here."),
            child=add,
        )
        empty.add_css_class("compact")
        return empty

    def _build_bottom_bar(self) -> Gtk.Widget:
        self.summary = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.combine_button = Gtk.Button(label=_("_Combine"), use_underline=True, halign=Gtk.Align.CENTER)
        self.combine_button.add_css_class("suggested-action")
        self.combine_button.add_css_class("pill")
        self.combine_button.connect("clicked", weakly(self._on_combine_clicked))
        bottom = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=18,
            margin_start=18,
            margin_end=18,
        )
        bottom.append(self.summary)
        bottom.append(self.combine_button)
        return bottom

    # The list

    def rows(self) -> list[FileRow]:
        rows = []
        child = self.list.get_first_child()
        while child is not None:
            if isinstance(child, FileRow):
                rows.append(child)
            child = child.get_next_sibling()
        return rows

    def paths(self) -> list[str]:
        """The files, in the order they will be combined."""
        return [row.path for row in self.rows()]

    def add_files(self, paths: Sequence[str], at: int | None = None) -> None:
        """Add files before file `at`, or at the end."""
        position = len(self.rows()) if at is None else at
        for offset, path in enumerate(paths):
            row = FileRow(path)
            drag = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
            drag.connect("begin", weakly(self._on_drag_pressed))
            drag.connect("end", weakly(self._on_drag_released))
            drag.connect("prepare", weakly(self._on_drag_prepare))
            drag.connect("drag-begin", weakly(self._on_drag_begin))
            drag.connect("drag-end", weakly(self._on_drag_end))
            row.add_controller(drag)
            row.connect("move-requested", weakly(self._on_move_requested))
            row.remove_button.connect("clicked", weakly(self._on_remove_clicked))
            row.unlock_button.connect("clicked", weakly(self._on_unlock_clicked))
            self.list.insert(row, position + offset)
        self._update()
        self._read_next()

    def move(self, index: int, to: int) -> bool:
        """Move file `index` to just before file `to`, counted before the move;
        the number of files puts it last. Says whether it moved."""
        rows = self.rows()
        if not (0 <= index < len(rows) and 0 <= to <= len(rows)):
            return False
        destination = to - 1 if to > index else to
        if destination == index:
            return False
        row = rows[index]
        focus = self.get_focus()
        inside = focus is not None and (focus is row or focus.is_ancestor(row))
        self.list.remove(row)
        self.list.insert(row, destination)
        self._update()
        # Back where it was: on the file, or on one of its buttons.
        if inside and not (focus.get_mapped() and focus.grab_focus()):
            row.grab_focus()
        return True

    def move_file(self, row: FileRow, move: str) -> None:
        """Make one of the moves of MOVE_KEYS."""
        rows = self.rows()
        if row not in rows:
            return
        index = rows.index(row)
        to = {"move-up": index - 1, "move-down": index + 2, "move-to-top": 0, "move-to-bottom": len(rows)}[move]
        if self.move(index, min(max(to, 0), len(rows))):
            # The number on its picture changed; screen readers say so.
            announce(
                row,
                _("Moved to position {position} of {count}").format(position=row.get_index() + 1, count=len(rows)),
            )

    def remove(self, row: FileRow) -> None:
        rows = self.rows()
        if row not in rows:
            return
        index = rows.index(row)
        had_focus = self._focused_row() is row
        self.list.remove(row)
        self._update()
        rest = self.rows()
        if had_focus and rest:
            rest[min(index, len(rest) - 1)].grab_focus()

    def _update(self) -> None:
        """Number the files, and say what Combine will make."""
        rows = self.rows()
        for number, row in enumerate(rows, start=1):
            row.set_place(number, len(rows))
        self.stack.set_visible_child_name("files" if rows else "empty")
        problems = [row for row in rows if row.problem is not None]
        reading = any(row.needs_reading for row in rows)
        self.combine_button.set_sensitive(bool(rows) and not problems)
        if problems:
            count = len(problems)
            text = ngettext(
                "{count} file can’t be combined as it is.", "{count} files can’t be combined as they are.", count
            ).format(count=count)
        elif reading:
            text = _("Reading the files…")
        elif rows:
            pages = sum(row.pages or 0 for row in rows)
            text = _("{files}, {pages}").format(
                files=ngettext("{count} file", "{count} files", len(rows)).format(count=len(rows)),
                pages=ngettext("{count} page", "{count} pages", pages).format(count=pages),
            )
            if any(row.password is not None for row in rows):
                text = _("{summary}. The new PDF won’t have a password.").format(summary=text)
        else:
            text = ""
        self.summary.set_label(text)
        self.summary.set_visible(bool(text))
        if problems:
            self.summary.remove_css_class("dim-label")
            self.summary.add_css_class("error")
        else:
            self.summary.remove_css_class("error")
            self.summary.add_css_class("dim-label")

    def _focused_row(self) -> FileRow | None:
        focus = self.get_focus()
        row = focus.get_ancestor(FileRow.__gtype__) if focus is not None else None
        return row if isinstance(row, FileRow) else None

    # Reading the files, one at a time

    def _read_next(self) -> None:
        if self._reading is not None or self._closed:
            return
        row = next((row for row in self.rows() if row.needs_reading), None)
        if row is None:
            if self._combine_when_read:
                self._combine_when_read = False
                self._on_combine_clicked()
            return
        self._reading = row
        self._engine.start()
        self._engine.request(
            {"op": "inspect", "path": row.path, "password": row.password, "size": PREVIEW_SIZE * 2},
            functools.partial(self._on_read, row),
        )

    def _on_read(self, row: FileRow, reply: dict, pixels: bytes) -> None:
        if self._reading is row:
            self._reading = None
        if reply.get("ok"):
            row.show_contents(reply, pixels)
        else:
            row.show_problem(str(reply.get("error")))
        self._update()
        self._read_next()

    def _on_engine_died(self, _engine: EngineClient) -> None:
        # One file at a time: the one being read is the one that did it.
        row, self._reading = self._reading, None
        if row is not None:
            row.show_problem("engine-failed")
        self._update()
        self._read_next()  # with a new engine

    # Buttons

    def _on_combine_clicked(self, *_args: object) -> None:
        rows = self.rows()
        if not rows or any(row.problem is not None for row in rows):
            return
        if any(row.needs_reading for row in rows):
            self._combine_when_read = True  # as soon as they are read
            return
        passwords = {row.path: row.password for row in rows if row.password is not None}
        self.emit("combine-requested", self.paths(), passwords)

    def _on_move_requested(self, row: FileRow, move: str) -> None:
        self.move_file(row, move)
        # The menu has closed: back to its button, to move the file again.
        row.menu_button.grab_focus()

    def _on_remove_clicked(self, button: Gtk.Button) -> None:
        row = button.get_ancestor(FileRow.__gtype__)
        if isinstance(row, FileRow):
            self.remove(row)

    def _on_add_clicked(self, *_args: object) -> None:
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(files_filter())
        dialog = Gtk.FileDialog(title=_("Add Files"), modal=True, filters=filters)
        rows = self.rows()
        if rows:  # start where the last file came from
            dialog.set_initial_folder(Gio.File.new_for_path(str(Path(rows[-1].path).parent)))
        root = self.get_root()
        dialog.open_multiple(root if isinstance(root, Gtk.Window) else None, None, weakly(self._on_files_chosen))

    def _on_files_chosen(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return  # closed without choosing
        paths = [path for file in files if (path := file.get_path()) is not None]
        if paths and not self._closed:
            self.add_files(paths)

    def _on_unlock_clicked(self, button: Gtk.Button) -> None:
        row = button.get_ancestor(FileRow.__gtype__)
        if not isinstance(row, FileRow):
            return
        entry = Gtk.PasswordEntry(show_peek_icon=True, activates_default=True)
        entry.update_property([Gtk.AccessibleProperty.LABEL], [_("Password")])
        if row.problem == "wrong-password":
            body = _("That password is not correct. Try again.")
        else:
            body = _("“{name}” is protected. Enter its password to combine it.").format(name=Path(row.path).name)
        dialog = Adw.AlertDialog(heading=_("Password Required"), body=body)
        dialog.add_response("cancel", _("_Cancel"))
        dialog.add_response("unlock", _("_Unlock"))
        dialog.set_response_appearance("unlock", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("unlock")
        dialog.set_close_response("cancel")
        dialog.set_extra_child(entry)
        dialog.connect("response", weakly(self._on_password_response))
        self._unlocking = (row, entry)
        dialog.present(self)
        dialog.set_focus(entry)

    def _on_password_response(self, _dialog: Adw.AlertDialog, response: str) -> None:
        unlocking, self._unlocking = self._unlocking, None
        if response == "unlock" and unlocking is not None and unlocking[0] in self.rows():
            self.unlock(unlocking[0], unlocking[1].get_text())

    def unlock(self, row: FileRow, password: str) -> None:
        """Read a locked file again, with this password."""
        row.password = password
        row.show_reading()
        self._update()
        self._read_next()

    # Keyboard

    def _on_key_pressed(
        self, _controller: Gtk.EventControllerKey, keyval: int, _keycode: int, state: Gdk.ModifierType
    ) -> bool:
        # The file with the focus: tinted, and ringed once keys are used.
        row = self._focused_row()
        if row is None:
            return False
        alt = bool(state & Gdk.ModifierType.ALT_MASK)
        move = next((move for move, keys in MOVE_KEYS.items() if keyval in keys), None)
        if alt and move is not None:
            self.move_file(row, move)
        elif keyval in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete) and not alt:
            self.remove(row)
        else:
            return False
        return True

    # Dragging and dropping

    def _on_drag_pressed(self, source: Gtk.DragSource, _sequence: Gdk.EventSequence | None) -> None:
        source.get_widget().set_cursor_from_name("grabbing")

    def _on_drag_released(self, source: Gtk.DragSource, _sequence: Gdk.EventSequence | None) -> None:
        source.get_widget().set_cursor_from_name("grab")

    def _on_drag_prepare(self, source: Gtk.DragSource, x: float, y: float) -> Gdk.ContentProvider | None:
        row = source.get_widget()
        if not isinstance(row, FileRow):
            return None
        self._drag_hotspot = (int(x), int(y))
        return Gdk.ContentProvider.new_for_value(f"{self._drag_tag}{row.get_index()}")

    def _on_drag_begin(self, source: Gtk.DragSource, _drag: Gdk.Drag) -> None:
        row = source.get_widget()
        source.set_icon(Gtk.WidgetPaintable.new(row), *self._drag_hotspot)
        row.add_css_class("bp-dragged")

    def _on_drag_end(self, source: Gtk.DragSource, _drag: Gdk.Drag, _deleted: bool) -> None:
        row = source.get_widget()
        row.remove_css_class("bp-dragged")
        row.set_cursor_from_name("grab")

    def drop_position(self, widget: Gtk.Widget, y: float) -> int:
        """Where something dropped at height `y` of `widget` goes: before the
        first file whose middle is lower down."""
        rows = self.rows()
        ok, point = widget.compute_point(self.list, Graphene.Point().init(0, y))
        if not ok:
            return len(rows)
        for index, row in enumerate(rows):
            found, bounds = row.compute_bounds(self.list)
            if found and point.y < bounds.get_y() + bounds.get_height() / 2:
                return index
        return len(rows)

    def _show_drop_place(self, at: int | None) -> None:
        rows = self.rows()
        for index, row in enumerate(rows):
            row.remove_css_class("bp-drop-before")
            row.remove_css_class("bp-drop-after")
            if at is not None and index == at:
                row.add_css_class("bp-drop-before")
            elif at is not None and at == len(rows) and index == len(rows) - 1:
                row.add_css_class("bp-drop-after")

    def _on_drop_motion(self, target: Gtk.DropTarget, _x: float, y: float) -> Gdk.DragAction:
        self._show_drop_place(self.drop_position(target.get_widget(), y))
        drop = target.get_current_drop()
        # Rows move within the list; files from elsewhere are copied in.
        return Gdk.DragAction.MOVE if drop is not None and drop.get_drag() is not None else Gdk.DragAction.COPY

    def _on_drop_leave(self, _target: Gtk.DropTarget) -> None:
        self._show_drop_place(None)

    def _on_drop(self, target: Gtk.DropTarget, value: object, _x: float, y: float) -> bool:
        at = self.drop_position(target.get_widget(), y)
        self._show_drop_place(None)
        if isinstance(value, Gdk.FileList):
            paths = [path for file in value.get_files() if (path := file.get_path()) is not None]
            if paths:
                self.add_files(paths, at)
            return bool(paths)
        if isinstance(value, str) and value.startswith(self._drag_tag):
            self.move(int(value.removeprefix(self._drag_tag)), at)
            return True
        return False

    def _on_closed(self, _dialog: Adw.Dialog) -> None:
        self._closed = True
        self._engine.close()

# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organize mode: every page as a tile in a grid, to select, reorder and change.

Pages can be selected with the mouse (Ctrl and Shift as usual) or the keyboard,
and moved by dragging or with Alt and the arrow keys, so that nothing depends
on dragging (plan, Milestone 2). Files dropped on the grid are inserted where
they land. The grid itself changes nothing: it asks the window for edits.
"""

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, GObject, Gtk  # noqa: E402

from ..engine_client import EngineClient  # noqa: E402
from ..i18n import _  # noqa: E402
from .thumbnails import ThumbnailRow, ThumbnailSidebar  # noqa: E402
from .weak import weakly  # noqa: E402


class OrganizeView(ThumbnailSidebar):
    """A grid of page tiles. Emits edit-requested and insert-requested."""

    __gtype_name__ = "BluepencilOrganizeView"
    __gsignals__: dict[str, tuple] = {
        # A request for the engine, such as {"action": "move", "pages": [2], "to": 0}.
        "edit-requested": (GObject.SignalFlags.RUN_LAST, None, (object,)),
        # Files to insert: (paths, before page).
        "insert-requested": (GObject.SignalFlags.RUN_LAST, None, (object, int)),
    }

    tile_width = 150
    tile_max_height = 212

    def __init__(self, engine: EngineClient, page_sizes: list[tuple[float, float]]) -> None:
        super().__init__(engine, page_sizes)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", weakly(self._on_key_pressed))
        self._list.add_controller(keys)
        # Files dropped between or after the tiles go at the end.
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", weakly(self._on_files_dropped_at_end))
        self.add_controller(drop)

    def _make_selection(self, store: Gio.ListStore) -> Gtk.SelectionModel:
        return Gtk.MultiSelection(model=store)

    def _make_view(self, selection: Gtk.SelectionModel, factory: Gtk.ListItemFactory) -> Gtk.Widget:
        view = Gtk.GridView(model=selection, factory=factory, vexpand=True, max_columns=12, enable_rubberband=True)
        view.update_property([Gtk.AccessibleProperty.LABEL], [_("Pages")])
        return view

    # Selection

    def selected_pages(self) -> list[int]:
        """The selected pages, from first to last."""
        selection = self._selection.get_selection()
        return [selection.get_nth(n) for n in range(selection.get_size())]

    def select_pages(self, pages: list[int]) -> None:
        """Select these pages, and only these, and bring the first into view."""
        self._selection.unselect_all()
        for index in pages:
            if 0 <= index < len(self.items):
                self._selection.select_item(index, False)
        if pages and self.get_mapped():
            self._list.scroll_to(pages[0], Gtk.ListScrollFlags.FOCUS, None)

    def show_page(self, index: int) -> None:
        if not self.selected_pages():
            self.select_pages([index])

    def reveal_selected(self) -> None:
        pages = self.selected_pages()
        if pages and self.get_mapped():
            self._list.scroll_to(pages[0], Gtk.ListScrollFlags.FOCUS, None)

    def focus_grid(self) -> None:
        self._list.grab_focus()

    def _on_selected(self, *_args: object) -> None:
        pass  # choosing pages here does not move the page view

    # Tiles

    def _on_setup(self, factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        super()._on_setup(factory, list_item)
        tile = list_item.get_child()
        drag = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        drag.connect("prepare", weakly(self._on_drag_prepare))
        drag.connect("drag-begin", weakly(self._on_drag_begin))
        tile.add_controller(drag)
        drop = Gtk.DropTarget(actions=Gdk.DragAction.MOVE | Gdk.DragAction.COPY)
        drop.set_gtypes([GObject.TYPE_STRING, Gdk.FileList])
        drop.connect("drop", weakly(self._on_drop_on_tile))
        tile.add_controller(drop)

    def _on_drag_prepare(self, source: Gtk.DragSource, _x: float, _y: float) -> Gdk.ContentProvider | None:
        tile = source.get_widget()
        if not isinstance(tile, ThumbnailRow) or tile.item is None:
            return None
        return Gdk.ContentProvider.new_for_value(f"bluepencil-page:{tile.item.index}")

    def _on_drag_begin(self, source: Gtk.DragSource, _drag: Gdk.Drag) -> None:
        tile = source.get_widget()
        if isinstance(tile, ThumbnailRow) and tile.item is not None and tile.item.props.texture is not None:
            source.set_icon(tile.item.props.texture, tile.sheet.size[0] // 2, tile.sheet.size[1] // 2)

    def _on_drop_on_tile(self, target: Gtk.DropTarget, value: object, x: float, _y: float) -> bool:
        tile = target.get_widget()
        if not isinstance(tile, ThumbnailRow) or tile.item is None:
            return False
        # The left half of a tile means before it, the right half after it.
        to = tile.item.index + (1 if x > tile.get_width() / 2 else 0)
        if isinstance(value, Gdk.FileList):
            return self._insert(value, to)
        if not isinstance(value, str) or not value.startswith("bluepencil-page:"):
            return False
        dragged = int(value.removeprefix("bluepencil-page:"))
        selected = self.selected_pages()
        pages = selected if dragged in selected else [dragged]
        self.emit("edit-requested", {"action": "move", "pages": pages, "to": to})
        return True

    def _on_files_dropped_at_end(self, _target: Gtk.DropTarget, value: object, _x: float, _y: float) -> bool:
        return isinstance(value, Gdk.FileList) and self._insert(value, len(self.items))

    def _insert(self, files: Gdk.FileList, at: int) -> bool:
        paths = [file.get_path() for file in files.get_files() if file.get_path() is not None]
        if not paths:
            return False
        self.emit("insert-requested", paths, at)
        return True

    # Keyboard

    def _on_key_pressed(
        self, _controller: Gtk.EventControllerKey, keyval: int, _keycode: int, state: Gdk.ModifierType
    ) -> bool:
        pages = self.selected_pages()
        if not pages:
            return False
        alt = bool(state & Gdk.ModifierType.ALT_MASK)
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete) and not alt:
            self.emit("edit-requested", {"action": "delete", "pages": pages})
        elif alt and keyval in (Gdk.KEY_Left, Gdk.KEY_Up, Gdk.KEY_KP_Left, Gdk.KEY_KP_Up) and pages[0] > 0:
            self.emit("edit-requested", {"action": "move", "pages": pages, "to": pages[0] - 1})
        elif alt and keyval in (Gdk.KEY_Right, Gdk.KEY_Down, Gdk.KEY_KP_Right, Gdk.KEY_KP_Down):
            if pages[-1] < len(self.items) - 1:
                self.emit("edit-requested", {"action": "move", "pages": pages, "to": pages[-1] + 2})
        else:
            return False
        return True

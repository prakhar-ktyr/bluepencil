# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The thumbnail sidebar: a small picture of every page, to see where you are
and jump elsewhere.

Thumbnails are rendered only for rows inside the sidebar's visible area, after
the full-size pages on screen (plan, D1 and D3), and only so many are kept.
GTK prepares many more rows than it shows (about 200, even while the sidebar
is hidden), so the rows' real positions decide what gets rendered.
"""

import collections
import functools

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gdk, Gio, GLib, GObject, Graphene, Gtk  # noqa: E402

from ..engine_client import EngineClient  # noqa: E402
from ..i18n import _  # noqa: E402
from .document_view import device_scale, scaling_filter  # noqa: E402
from .weak import weakly  # noqa: E402

#: Largest thumbnail, in logical pixels.
THUMBNAIL_WIDTH = 120
THUMBNAIL_MAX_HEIGHT = 170
#: Engine priority: after the pages on screen (0) and beside it (1).
THUMBNAIL_PRIORITY = 2
#: Thumbnails kept before the least recently shown ones are dropped.
MAX_THUMBNAILS = 400
#: Rows this far outside the visible area, as a share of its height, are
#: rendered ahead of time.
LOOKAHEAD = 0.5
#: After scrolling stops, look once more when the list has settled.
SETTLE_MS = 150


def thumbnail_size(width_pt: float, height_pt: float) -> tuple[int, int]:
    scale = min(THUMBNAIL_WIDTH / width_pt, THUMBNAIL_MAX_HEIGHT / height_pt)
    return max(1, round(width_pt * scale)), max(1, round(height_pt * scale))


class PageItem(GObject.Object):
    """One page in the list. `texture` is its thumbnail, once rendered."""

    __gtype_name__ = "BluepencilPageItem"

    texture = GObject.Property(type=Gdk.Texture)

    def __init__(self, index: int, width_pt: float, height_pt: float) -> None:
        super().__init__()
        self.index = index
        self.width_pt = width_pt
        self.height_pt = height_pt


class ThumbnailSheet(Gtk.Widget):
    """A white sheet of a fixed size, showing the thumbnail once it arrives."""

    __gtype_name__ = "BluepencilThumbnailSheet"

    def __init__(self) -> None:
        super().__init__(halign=Gtk.Align.CENTER)
        self.size = (THUMBNAIL_WIDTH, THUMBNAIL_WIDTH)
        self.texture: Gdk.Texture | None = None
        self.add_css_class("bp-page")

    def show(self, size: tuple[int, int], texture: Gdk.Texture | None) -> None:
        if size != self.size:
            self.size = size
            self.queue_resize()
        self.texture = texture
        self.queue_draw()

    def do_measure(self, orientation: Gtk.Orientation, for_size: int) -> tuple[int, int, int, int]:
        value = self.size[0] if orientation == Gtk.Orientation.HORIZONTAL else self.size[1]
        return value, value, -1, -1

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        if self.texture is not None:
            bounds = Graphene.Rect().init(0, 0, self.get_width(), self.get_height())
            snapshot.append_scaled_texture(self.texture, scaling_filter(self.texture, self), bounds)


class ThumbnailRow(Gtk.Box):
    """One row of the list. The list reuses rows for different pages."""

    __gtype_name__ = "BluepencilThumbnailRow"

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6, margin_bottom=6)
        self.sheet = ThumbnailSheet()
        self.label = Gtk.Label(halign=Gtk.Align.CENTER)
        self.label.add_css_class("caption")
        self.append(self.sheet)
        self.append(self.label)
        self.item: PageItem | None = None
        self._handler = 0

    def bind(self, item: PageItem) -> None:
        self.item = item
        self.label.set_label(str(item.index + 1))
        self.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Page {number}").format(number=item.index + 1)]
        )
        self._handler = item.connect("notify::texture", weakly(self._on_texture))
        self._on_texture(item)

    def unbind(self) -> None:
        if self.item is not None and self._handler:
            self.item.disconnect(self._handler)
        self.item = None
        self._handler = 0
        self.sheet.show(self.sheet.size, None)

    def _on_texture(self, item: PageItem, *_args: object) -> None:
        self.sheet.show(thumbnail_size(item.width_pt, item.height_pt), item.props.texture)


class ThumbnailSidebar(Gtk.Box):
    """Thumbnails of every page. Emits page-chosen when the user picks one."""

    __gtype_name__ = "BluepencilThumbnailSidebar"
    __gsignals__ = {
        # (page index, activated): activated is True for Enter or a double click.
        "page-chosen": (GObject.SignalFlags.RUN_LAST, None, (int, bool)),
    }

    def __init__(self, engine: EngineClient, page_sizes: list[tuple[float, float]]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._engine = engine
        self.items = [PageItem(i, width, height) for i, (width, height) in enumerate(page_sizes)]
        #: Rows GTK has prepared, by page; thumbnails on their way.
        self._rows: dict[int, ThumbnailRow] = {}
        self._requested: set[int] = set()
        #: Pages that have a thumbnail, least recently shown first.
        self._kept: collections.OrderedDict[int, None] = collections.OrderedDict()
        self._following = False
        self._update_queued = False
        self._settle_timer = 0
        #: Whether the sidebar is open. A closed one stays live, slid out of
        #: sight, so it cannot tell by itself.
        self._open = False

        store = Gio.ListStore.new(PageItem)
        store.splice(0, 0, self.items)
        self._selection = Gtk.SingleSelection(model=store, autoselect=True, can_unselect=False)
        # Handlers on things this sidebar owns are connected weakly (see weak.py).
        self._selection.connect("notify::selected", weakly(self._on_selected))

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", weakly(self._on_setup))
        factory.connect("bind", weakly(self._on_bind))
        factory.connect("unbind", weakly(self._on_unbind))
        self._list = Gtk.ListView(model=self._selection, factory=factory, vexpand=True)
        self._list.add_css_class("navigation-sidebar")
        self._list.update_property([Gtk.AccessibleProperty.LABEL], [_("Page thumbnails")])
        self._list.connect("activate", weakly(self._on_activate))
        self._scroller = Gtk.ScrolledWindow(child=self._list, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.append(self._scroller)

        adjustment = self._scroller.get_vadjustment()
        adjustment.connect("value-changed", weakly(self._on_scrolled))
        adjustment.connect("changed", weakly(self._on_scrolled))
        self.connect("map", self._on_scrolled)

    @property
    def selected(self) -> int:
        return self._selection.get_selected()

    def show_page(self, index: int) -> None:
        """Follow the page view: select page `index` and keep it in sight."""
        if index != self._selection.get_selected():
            self._following = True
            try:
                self._selection.set_selected(index)
            finally:
                self._following = False
        self.reveal_selected()

    def reveal_selected(self) -> None:
        if self.get_mapped():
            self._list.scroll_to(self._selection.get_selected(), Gtk.ListScrollFlags.NONE, None)

    def set_open(self, is_open: bool) -> None:
        """Render thumbnails only while the sidebar is open."""
        self._open = is_open
        if is_open:
            self._queue_update()
        else:
            for index in list(self._requested):
                self._cancel(index)

    def restart_rendering(self) -> None:
        """Ask again for thumbnails that were on their way, after an engine restart."""
        self._requested.clear()
        self._queue_update()

    # The list

    def _on_setup(self, _factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        list_item.set_child(ThumbnailRow())

    def _on_bind(self, _factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        item = list_item.get_item()
        row = list_item.get_child()
        row.bind(item)
        self._rows[item.index] = row
        if item.index in self._kept:
            self._kept.move_to_end(item.index)
        self._queue_update()

    def _on_unbind(self, _factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        item = list_item.get_item()
        list_item.get_child().unbind()
        self._rows.pop(item.index, None)
        self._cancel(item.index)

    def _on_selected(self, selection: Gtk.SingleSelection, _pspec: GObject.ParamSpec) -> None:
        if not self._following:
            self.emit("page-chosen", selection.get_selected(), False)

    def _on_activate(self, _list: Gtk.ListView, position: int) -> None:
        self.emit("page-chosen", position, True)

    # Rendering

    def _on_scrolled(self, *_args: object) -> None:
        self._queue_update()
        # Rows move into place on the next frame; look again once they have.
        if self._settle_timer:
            GLib.source_remove(self._settle_timer)
        self._settle_timer = GLib.timeout_add(SETTLE_MS, self._on_settled)

    def _on_settled(self) -> bool:
        self._settle_timer = 0
        self._update()
        return GLib.SOURCE_REMOVE

    def _queue_update(self) -> None:
        if not self._update_queued:
            self._update_queued = True
            GLib.idle_add(self._update)

    def _update(self) -> bool:
        self._update_queued = False
        height = self._scroller.get_height()
        if not self._open or not self.get_mapped() or height <= 0 or self._scroller.get_width() <= 0:
            return GLib.SOURCE_REMOVE
        reach = height * LOOKAHEAD
        origin = Graphene.Point().init(0, 0)
        for index, row in list(self._rows.items()):
            placed, point = row.compute_point(self._scroller, origin)
            top, bottom = point.y, point.y + row.get_height()
            wanted = placed and bottom > top and -reach <= bottom and top <= height + reach
            if wanted and row.item is not None and row.item.props.texture is None:
                self._request(row.item)
            elif not wanted:
                self._cancel(index)
        return GLib.SOURCE_REMOVE

    def _request(self, item: PageItem) -> None:
        if item.index in self._requested:
            return
        self._requested.add(item.index)
        width, _height = thumbnail_size(item.width_pt, item.height_pt)
        scale = width / item.width_pt * device_scale(self)
        self._engine.request(
            {"op": "render", "page": item.index, "scale": scale},
            functools.partial(self._on_rendered, item),
            priority=THUMBNAIL_PRIORITY,
            key=("thumbnail", item.index),
        )

    def _cancel(self, index: int) -> None:
        if index in self._requested:
            # Scrolled past before its turn came: no need to render it.
            self._engine.cancel(("thumbnail", index))
            self._requested.discard(index)

    def _on_rendered(self, item: PageItem, reply: dict, pixels: bytes) -> None:
        self._requested.discard(item.index)
        if not reply.get("ok"):
            return
        item.props.texture = Gdk.MemoryTexture.new(
            reply["width"],
            reply["height"],
            Gdk.MemoryFormat.R8G8B8,
            GLib.Bytes.new(pixels),
            reply["stride"],
        )
        self._kept[item.index] = None
        self._kept.move_to_end(item.index)
        self._trim()

    def _trim(self) -> None:
        excess = len(self._kept) - MAX_THUMBNAILS
        if excess <= 0:
            return
        unused = [index for index in self._kept if index not in self._rows][:excess]
        for index in unused:
            del self._kept[index]
            self.items[index].props.texture = None

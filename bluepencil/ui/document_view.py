# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The continuous page view.

Every page gets a white placeholder of the right size straight away, so the
scrollbar is right from the start. Only the pages on screen, and a few on
either side, are rendered (plan, D3). Rendered pages are kept up to a memory
limit, and the ones farthest from view are dropped first.
"""

import bisect
import functools
import math

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gdk, GLib, GObject, Graphene, Gsk, Gtk  # noqa: E402

from ..core.limits import limit_scale  # noqa: E402
from ..engine_client import EngineClient  # noqa: E402
from ..i18n import _  # noqa: E402

#: At 100 % a page appears at its printed size: PDF points are 1/72 inch and
#: the screen has 96 logical pixels per inch.
PIXELS_PER_POINT = 96 / 72
PAGE_GAP = 12
MARGIN = 16
MIN_ZOOM = 0.25
MAX_ZOOM = 8.0
ZOOM_STEP = 1.2
#: How far the arrow keys scroll, in pixels.
ARROW_STEP = 48
#: Pages rendered ahead of time beyond each edge of the screen.
PREFETCH = 2
#: Memory for rendered pages before the farthest ones are dropped.
CACHE_BYTES = 256 * 1024 * 1024


class FitMode:
    WIDTH = "width"
    PAGE = "page"


def device_scale(widget: Gtk.Widget) -> float:
    """Device pixels per logical pixel where `widget` is shown (2.0 on HiDPI)."""
    native = widget.get_native()
    surface = native.get_surface() if native is not None else None
    if surface is not None:
        return surface.get_scale()
    return float(widget.get_scale_factor())


def _same_scale(a: float, b: float) -> bool:
    """True when two render scales are close enough to look identical."""
    return a > 0 and b > 0 and abs(a - b) <= 0.02 * b


class PageWidget(Gtk.Widget):
    """One page: a white sheet, then the rendered image once it arrives."""

    __gtype_name__ = "BluepencilPageWidget"

    def __init__(self, index: int, width_pt: float, height_pt: float) -> None:
        super().__init__(halign=Gtk.Align.CENTER)
        self.index = index
        self.width_pt = width_pt
        self.height_pt = height_pt
        self.zoom = 1.0
        self.texture: Gdk.Texture | None = None
        #: Pixels per point of the image shown, and of the one on its way.
        self.texture_scale = 0.0
        self.requested_scale = 0.0
        #: Set when the engine could not render this page.
        self.failed = False
        self.add_css_class("bp-page")
        self.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Page {number}").format(number=index + 1)]
        )

    def pixel_size(self) -> tuple[int, int]:
        scale = self.zoom * PIXELS_PER_POINT
        return max(1, round(self.width_pt * scale)), max(1, round(self.height_pt * scale))

    @property
    def texture_bytes(self) -> int:
        if self.texture is None:
            return 0
        return self.texture.get_width() * self.texture.get_height() * 4

    def set_texture(self, texture: Gdk.Texture, scale: float) -> None:
        self.texture = texture
        self.texture_scale = scale
        self.queue_draw()

    def drop_texture(self) -> None:
        self.texture = None
        self.texture_scale = 0.0
        self.queue_draw()

    def do_measure(self, orientation: Gtk.Orientation, for_size: int) -> tuple[int, int, int, int]:
        width, height = self.pixel_size()
        size = width if orientation == Gtk.Orientation.HORIZONTAL else height
        return size, size, -1, -1

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        # The white sheet and its shadow come from the "bp-page" style. While
        # a sharper image is on its way, the old one is stretched to fit.
        if self.texture is not None:
            bounds = Graphene.Rect().init(0, 0, self.get_width(), self.get_height())
            snapshot.append_scaled_texture(self.texture, Gsk.ScalingFilter.TRILINEAR, bounds)


class DocumentView(Gtk.Box):
    """A scrolling column of pages for one open document."""

    __gtype_name__ = "BluepencilDocumentView"
    __gsignals__ = {
        "current-page-changed": (GObject.SignalFlags.RUN_LAST, None, (int,)),
        "zoom-changed": (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    def __init__(
        self,
        engine: EngineClient,
        page_sizes: list[tuple[float, float]],
        *,
        zoom: float = 1.0,
        fit: str | None = FitMode.WIDTH,
        page: int = 0,
    ) -> None:
        """Show pages of the given sizes, starting at `page` and `zoom`.

        With `fit` set, the zoom follows the window instead.
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        self._engine = engine
        self.pages = [PageWidget(i, width, height) for i, (width, height) in enumerate(page_sizes)]

        self._column = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=PAGE_GAP,
            halign=Gtk.Align.CENTER,
            margin_top=MARGIN,
            margin_bottom=MARGIN,
            margin_start=MARGIN,
            margin_end=MARGIN,
            focusable=True,
        )
        self._column.update_property([Gtk.AccessibleProperty.LABEL], [_("Pages")])
        for sheet in self.pages:
            self._column.append(sheet)
        self._scroller = Gtk.ScrolledWindow(child=self._column, hexpand=True, vexpand=True)
        self.append(self._scroller)

        self._zoom = min(MAX_ZOOM, max(MIN_ZOOM, zoom))
        self._fit = fit
        for sheet in self.pages:
            sheet.zoom = self._zoom
        #: The page to start at, until the view has a size and can go there.
        self._start_page: int | None = min(page, len(self.pages) - 1) if page > 0 else None
        self._offsets: list[int] | None = None
        #: (page, scroll position) after go_to_page, so the page asked for
        #: stays current even if the page after it shows more.
        self._pinned: tuple[int, float] | None = None
        self._current_page = 0
        self._wanted: set[int] = set()
        self._update_queued = False
        #: Size of the visible area, as last seen.
        self._size = (0, 0)
        self._pinch_start = 1.0

        vertical = self._scroller.get_vadjustment()
        vertical.connect("value-changed", lambda *_args: self.queue_update())
        vertical.connect("changed", self._on_viewport_changed)
        self._scroller.get_hadjustment().connect("changed", self._on_viewport_changed)
        self.connect("map", lambda *_args: self.queue_update())
        self.connect("notify::scale-factor", lambda *_args: self.queue_update())

        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)

        pinch = Gtk.GestureZoom()
        pinch.connect("begin", self._on_pinch_begin)
        pinch.connect("scale-changed", self._on_pinch)
        self.add_controller(pinch)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key_pressed)
        self.add_controller(keys)

        click = Gtk.GestureClick()
        click.connect("pressed", lambda *_args: self._column.grab_focus())
        self._column.add_controller(click)

    # Public API

    @property
    def zoom(self) -> float:
        """1.0 shows pages at their printed size."""
        return self._zoom

    @property
    def fit_mode(self) -> str | None:
        return self._fit

    @property
    def current_page(self) -> int:
        if self._start_page is not None:
            return self._start_page
        return self._current_page

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def focus_pages(self) -> None:
        self._column.grab_focus()

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom * ZOOM_STEP)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom / ZOOM_STEP)

    def fit(self, mode: str) -> None:
        """Keep pages as wide as the window, or whole pages on screen."""
        self._fit = mode
        self._refit()

    def set_zoom(self, zoom: float, fit: str | None = None) -> None:
        """Show pages at `zoom`. Fitting stops unless `fit` is given again."""
        zoom = min(MAX_ZOOM, max(MIN_ZOOM, zoom))
        self._fit = fit
        if not math.isclose(zoom, self._zoom, rel_tol=1e-4):
            index, fraction = self._position()
            across = self._horizontal_centre()
            self._zoom = zoom
            self._offsets = None
            for page in self.pages:
                page.zoom = zoom
                page.queue_resize()
            # Move the scrollbars to the same spot in the new layout now, before
            # GTK lays it out. Moving them from inside GTK's layout pass is
            # ignored for drawing, which left the old spot on screen.
            self._configure_scrolling(index, fraction, across)
            self.queue_update()
        self.emit("zoom-changed")

    def go_to_page(self, index: int) -> None:
        """Scroll so that page `index` (from 0) starts at the top of the screen."""
        index = min(max(index, 0), len(self.pages) - 1)
        if self._start_page is not None:
            self._start_page = index  # it goes there once the view has a size
            return
        vertical = self._scroller.get_vadjustment()
        vertical.set_value(max(0.0, self._page_offsets()[index] - MARGIN))
        self._pinned = (index, vertical.get_value())
        self._set_current_page(index)

    def restart_rendering(self) -> None:
        """Forget renders that were on their way, after an engine restart."""
        for page in self.pages:
            page.requested_scale = 0.0
            page.failed = False
        self._wanted.clear()
        self.queue_update()

    def queue_update(self) -> None:
        if not self._update_queued:
            self._update_queued = True
            GLib.idle_add(self._update)

    # Layout

    def _on_viewport_changed(self, _adjustment: Gtk.Adjustment) -> None:
        # Runs inside GTK's layout pass: only note the size and schedule work.
        size = (
            round(self._scroller.get_hadjustment().get_page_size()),
            round(self._scroller.get_vadjustment().get_page_size()),
        )
        if size != self._size:
            self._size = size
            if self._fit is not None:
                GLib.idle_add(self._refit)
            if self._start_page is not None and min(size) > 0:
                # After the refit, so that the page is found at its final zoom.
                GLib.idle_add(self._go_to_start_page)
        self.queue_update()

    def _go_to_start_page(self) -> bool:
        if self._start_page is not None:
            index, self._start_page = self._start_page, None
            self.go_to_page(index)
            self.queue_update()
        return GLib.SOURCE_REMOVE

    def _refit(self) -> bool:
        if self._fit is not None:
            zoom = self._fit_zoom(self._fit)
            if zoom is not None:
                self.set_zoom(zoom, fit=self._fit)
        return GLib.SOURCE_REMOVE

    def _fit_zoom(self, mode: str) -> float | None:
        width = self._size[0] - 2 * MARGIN
        height = self._size[1] - 2 * MARGIN
        if width <= 0 or height <= 0:
            return None
        zoom = width / (max(page.width_pt for page in self.pages) * PIXELS_PER_POINT)
        if mode == FitMode.PAGE:
            tallest = max(page.height_pt for page in self.pages) * PIXELS_PER_POINT
            zoom = min(zoom, height / tallest)
        return zoom

    def _page_offsets(self) -> list[int]:
        """Where each page starts inside the column, matching Gtk.Box's layout."""
        if self._offsets is None:
            offsets, y = [], MARGIN
            for page in self.pages:
                offsets.append(y)
                y += page.pixel_size()[1] + PAGE_GAP
            self._offsets = offsets
        return self._offsets

    def _content_size(self) -> tuple[int, int]:
        """Size of the column of pages, matching Gtk.Box's layout."""
        offsets = self._page_offsets()
        width = max(page.pixel_size()[0] for page in self.pages) + 2 * MARGIN
        return width, offsets[-1] + self.pages[-1].pixel_size()[1] + MARGIN

    def _position(self) -> tuple[int, float]:
        """The page at the top of the screen, and how far down it the screen starts."""
        offsets = self._page_offsets()
        top = self._scroller.get_vadjustment().get_value()
        index = max(0, bisect.bisect_right(offsets, top) - 1)
        return index, (top - offsets[index]) / self.pages[index].pixel_size()[1]

    def _horizontal_centre(self) -> float:
        """Where the middle of the screen is across the column, from 0 to 1."""
        horizontal = self._scroller.get_hadjustment()
        upper = horizontal.get_upper()
        if upper <= 0:
            return 0.5
        return (horizontal.get_value() + horizontal.get_page_size() / 2) / upper

    def _configure_scrolling(self, index: int, fraction: float, across: float) -> None:
        width, height = self._content_size()
        vertical = self._scroller.get_vadjustment()
        visible = vertical.get_page_size()
        upper = max(height, visible)
        value = self._page_offsets()[index] + fraction * self.pages[index].pixel_size()[1]
        vertical.configure(
            min(max(value, 0.0), upper - visible),
            0.0,
            upper,
            vertical.get_step_increment(),
            vertical.get_page_increment(),
            visible,
        )
        horizontal = self._scroller.get_hadjustment()
        visible = horizontal.get_page_size()
        upper = max(width, visible)
        horizontal.configure(
            min(max(across * upper - visible / 2, 0.0), upper - visible),
            0.0,
            upper,
            horizontal.get_step_increment(),
            horizontal.get_page_increment(),
            visible,
        )

    def _visible_range(self) -> tuple[int, int]:
        adjustment = self._scroller.get_vadjustment()
        top = adjustment.get_value()
        bottom = top + adjustment.get_page_size()
        offsets = self._page_offsets()
        first = max(0, bisect.bisect_right(offsets, top) - 1)
        last = max(first, bisect.bisect_right(offsets, bottom) - 1)
        return first, min(last, len(self.pages) - 1)

    def _most_visible(self, first: int, last: int) -> int:
        adjustment = self._scroller.get_vadjustment()
        top = adjustment.get_value()
        bottom = top + adjustment.get_page_size()
        offsets = self._page_offsets()
        best, best_height = first, -math.inf
        for index in range(first, last + 1):
            start = offsets[index]
            end = start + self.pages[index].pixel_size()[1]
            shown = min(end, bottom) - max(start, top)
            if shown > best_height:
                best, best_height = index, shown
        return best

    def _set_current_page(self, index: int) -> None:
        if index != self._current_page:
            self._current_page = index
            self.emit("current-page-changed", index)

    # Rendering

    def _target_scale(self, page: PageWidget) -> float:
        scale = self._zoom * PIXELS_PER_POINT * device_scale(self)
        return limit_scale(page.width_pt, page.height_pt, scale)

    def _update(self) -> bool:
        self._update_queued = False
        if not self.get_mapped() or not self.pages or self._start_page is not None:
            return GLib.SOURCE_REMOVE
        first, last = self._visible_range()
        start = max(0, first - PREFETCH)
        end = min(len(self.pages) - 1, last + PREFETCH)
        wanted = set(range(start, end + 1))
        for index in self._wanted - wanted:
            page = self.pages[index]
            if page.requested_scale:
                self._engine.cancel(("render", index))
                page.requested_scale = 0.0
        self._wanted = wanted

        on_screen = list(range(first, last + 1))
        nearby = [i for i in range(start, end + 1) if i < first or i > last]
        for index in on_screen + nearby:
            page = self.pages[index]
            target = self._target_scale(page)
            if page.failed or _same_scale(page.texture_scale, target) or _same_scale(page.requested_scale, target):
                continue
            page.requested_scale = target
            self._engine.request(
                {"op": "render", "page": index, "scale": target},
                functools.partial(self._on_rendered, index, target),
                priority=0 if first <= index <= last else 1,
                key=("render", index),
            )

        value = self._scroller.get_vadjustment().get_value()
        if self._pinned is not None and abs(self._pinned[1] - value) < 1:
            current = self._pinned[0]
        else:
            self._pinned = None
            current = self._most_visible(first, last)
        self._set_current_page(current)
        return GLib.SOURCE_REMOVE

    def _on_rendered(self, index: int, scale: float, reply: dict, pixels: bytes) -> None:
        page = self.pages[index]
        if page.requested_scale == scale:
            page.requested_scale = 0.0
        if not reply.get("ok"):
            page.failed = True
            return
        texture = Gdk.MemoryTexture.new(
            reply["width"],
            reply["height"],
            Gdk.MemoryFormat.R8G8B8,
            GLib.Bytes.new(pixels),
            reply["stride"],
        )
        # Keep whichever image is closer to what the current zoom needs.
        target = self._target_scale(page)
        if page.texture is None or abs(scale - target) <= abs(page.texture_scale - target):
            page.set_texture(texture, scale)
        self._trim_cache()

    def _trim_cache(self) -> None:
        rendered = [page for page in self.pages if page.texture is not None]
        total = sum(page.texture_bytes for page in rendered)
        if total <= CACHE_BYTES:
            return
        farthest_first = sorted(rendered, key=lambda page: abs(page.index - self._current_page), reverse=True)
        for page in farthest_first:
            if page.index in self._wanted:
                continue
            total -= page.texture_bytes
            page.drop_texture()
            if total <= CACHE_BYTES:
                return

    # Input

    def _on_scroll(self, controller: Gtk.EventControllerScroll, _dx: float, dy: float) -> bool:
        if not controller.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK:
            return False
        if controller.get_unit() == Gdk.ScrollUnit.SURFACE:
            dy /= 40  # touchpads report pixels, mouse wheels report steps
        if dy:
            self.set_zoom(self._zoom * ZOOM_STEP ** -dy)
        return True

    def _on_pinch_begin(self, _gesture: Gtk.GestureZoom, _sequence: object) -> None:
        self._pinch_start = self._zoom

    def _on_pinch(self, _gesture: Gtk.GestureZoom, scale: float) -> None:
        self.set_zoom(self._pinch_start * scale)

    def _on_key_pressed(
        self, _controller: Gtk.EventControllerKey, keyval: int, _keycode: int, state: Gdk.ModifierType
    ) -> bool:
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK):
            return False
        vertical = self._scroller.get_vadjustment()
        horizontal = self._scroller.get_hadjustment()
        screen = vertical.get_page_size() * 0.9
        if keyval in (Gdk.KEY_Home, Gdk.KEY_KP_Home):
            self.go_to_page(0)
        elif keyval in (Gdk.KEY_End, Gdk.KEY_KP_End):
            vertical.set_value(vertical.get_upper())
        elif keyval in (Gdk.KEY_Page_Down, Gdk.KEY_KP_Page_Down):
            _scroll(vertical, screen)
        elif keyval in (Gdk.KEY_Page_Up, Gdk.KEY_KP_Page_Up):
            _scroll(vertical, -screen)
        elif keyval == Gdk.KEY_space:
            _scroll(vertical, -screen if state & Gdk.ModifierType.SHIFT_MASK else screen)
        elif keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
            _scroll(vertical, ARROW_STEP)
        elif keyval in (Gdk.KEY_Up, Gdk.KEY_KP_Up):
            _scroll(vertical, -ARROW_STEP)
        elif keyval in (Gdk.KEY_Right, Gdk.KEY_KP_Right):
            _scroll(horizontal, ARROW_STEP)
        elif keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left):
            _scroll(horizontal, -ARROW_STEP)
        else:
            return False
        return True


def _scroll(adjustment: Gtk.Adjustment, delta: float) -> None:
    adjustment.set_value(adjustment.get_value() + delta)

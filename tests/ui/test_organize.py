# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organize mode: the page grid and its tools."""

import gi
import pymupdf

gi.require_version("Gdk", "4.0")
gi.require_version("Gio", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, Gtk  # noqa: E402

from .helpers import loaded  # noqa: E402
from .test_editing import settled  # noqa: E402

#: Pages of different widths, so that their order can be read from the sizes.
SIZES = [(300, 800), (400, 800), (500, 800), (600, 800), (700, 800)]


def widths(window) -> list[int]:
    return [round(width) for width, _height in window._page_sizes]


def organize(window) -> None:
    window.activate_action("win.organize", None)


def grid_shown(window) -> bool:
    """the page grid, with its first tile drawn"""
    grid = window.organize
    return (
        grid is not None
        and window._stack.get_visible_child() is grid
        and grid.items[0].props.texture is not None
        and not window._busy
    )


def test_the_grid_shows_every_page_with_the_current_one_selected(run_app, make_pdf):
    def go_to_third_page_and_organize(window) -> None:
        window.view.go_to_page(2)
        organize(window)

    def check(window) -> None:
        grid = window.organize
        assert len(grid.items) == 5
        assert grid.selected_pages() == [2]
        assert window._organize_bar.get_visible() and not window._bottom_bar.get_visible()
        organize(window)  # and back

    def back_to_reading(window) -> bool:
        return window._stack.get_visible_child() is window._split

    def check_back(window) -> None:
        assert window.view.current_page == 2
        assert window._bottom_bar.get_visible() and not window._organize_bar.get_visible()

    run_app(
        (loaded, go_to_third_page_and_organize),
        (grid_shown, check),
        (back_to_reading, check_back),
        argv=[make_pdf(pages=5)],
    )


def test_tools_act_on_all_selected_pages_and_keep_them_selected(run_app, make_pdf):
    def rotate_two(window) -> None:
        window.organize.select_pages([1, 3])
        window.activate_action("win.rotate-right", None)

    def check_rotated(window) -> None:
        assert [rotated for rotated, (w, h) in enumerate(window._page_sizes) if w > h] == [1, 3]
        assert window.organize.selected_pages() == [1, 3]
        window.activate_action("win.duplicate-pages", None)

    def check_duplicated(window) -> None:
        assert len(window._page_sizes) == 7
        assert window.organize.selected_pages() == [2, 5]  # the copies
        window.activate_action("win.delete-page", None)

    def check_deleted(window) -> None:
        assert len(window._page_sizes) == 5
        assert window.organize.selected_pages() == [4]  # the page after the last one deleted

    def pages(count):
        def condition(window) -> bool:
            return grid_shown(window) and len(window._page_sizes) == count

        condition.__doc__ = f"{count} pages in the grid"
        return condition

    def changed(window) -> bool:
        """the change to arrive"""
        return grid_shown(window) and bool(window._state.get("modified"))

    run_app(
        (loaded, organize),
        (grid_shown, rotate_two),
        (changed, check_rotated),
        (pages(7), check_duplicated),
        (pages(5), check_deleted),
        argv=[make_pdf(pages=5)],
    )


def press(widget_owner, keyval: int, modifiers: Gdk.ModifierType) -> None:
    """A key press, as the grid's key handler receives it."""
    widget_owner._on_key_pressed(None, keyval, 0, modifiers)


def test_pages_move_with_alt_and_the_arrow_keys(run_app, make_pdf):
    def move_last_left(window) -> None:
        window.organize.select_pages([4])
        press(window.organize, Gdk.KEY_Left, Gdk.ModifierType.ALT_MASK)

    def moved(window) -> bool:
        """the page to move"""
        return grid_shown(window) and widths(window) == [300, 400, 500, 700, 600]

    def move_first_right(window) -> None:
        assert window.organize.selected_pages() == [3]
        window.organize.select_pages([0])
        press(window.organize, Gdk.KEY_Right, Gdk.ModifierType.ALT_MASK)

    def moved_again(window) -> bool:
        """the first page to move right"""
        return grid_shown(window) and widths(window) == [400, 300, 500, 700, 600]

    def delete_with_the_key(window) -> None:
        press(window.organize, Gdk.KEY_Delete, Gdk.ModifierType(0))

    def deleted(window) -> bool:
        """the page to be deleted"""
        return grid_shown(window) and widths(window) == [400, 500, 700, 600]

    run_app(
        (loaded, organize),
        (grid_shown, move_last_left),
        (moved, move_first_right),
        (moved_again, delete_with_the_key),
        (deleted, lambda window: None),
        argv=[make_pdf(sizes=SIZES, pages=5)],
    )


def drop_target_of(tile: Gtk.Widget) -> Gtk.DropTarget:
    controllers = tile.observe_controllers()
    return next(
        controllers.get_item(n)
        for n in range(controllers.get_n_items())
        if isinstance(controllers.get_item(n), Gtk.DropTarget)
    )


def test_dragging_selected_pages_onto_a_tile_moves_them(run_app, make_pdf):
    def drag(window) -> None:
        grid = window.organize
        grid.select_pages([0, 1])
        tile = grid._rows[3]
        # Dropped on the right half of page 4: after it.
        assert grid._on_drop_on_tile(drop_target_of(tile), "bluepencil-page:1", tile.get_width() * 0.75, 10)

    def moved(window) -> bool:
        """the pages to move"""
        return grid_shown(window) and widths(window) == [500, 600, 300, 400, 700]

    def check(window) -> None:
        assert window.organize.selected_pages() == [2, 3]

    run_app((loaded, organize), (grid_shown, drag), (moved, check), argv=[make_pdf(sizes=SIZES, pages=5)])


def test_files_dropped_on_the_grid_are_inserted_where_they_land(run_app, make_pdf):
    other = make_pdf("other.pdf", pages=2, size=(222, 333))

    def drop(window) -> None:
        window.organize.emit("insert-requested", [str(other)], 1)

    def inserted(window) -> bool:
        """the pages to arrive"""
        return grid_shown(window) and len(window._page_sizes) == 5

    def check(window) -> None:
        assert widths(window) == [300, 222, 222, 400, 500]
        assert window.organize.selected_pages() == [1, 2]

    run_app((loaded, organize), (grid_shown, drop), (inserted, check), argv=[make_pdf(sizes=SIZES, pages=3)])


def test_extract_writes_the_selected_pages_and_changes_nothing(run_app, make_pdf, tmp_path):
    target = tmp_path / "chosen"

    def extract(window) -> None:
        window.organize.select_pages([0, 2])
        window.extract_pages(window.organize.selected_pages(), str(target))

    def written(window) -> bool:
        """the new file"""
        return settled(window) and (tmp_path / "chosen.pdf").exists()

    def check(window) -> None:
        assert not window._state.get("modified")
        extracted = pymupdf.open(tmp_path / "chosen.pdf")
        assert [round(page.rect.width) for page in extracted.pages()] == [300, 500]

    run_app((loaded, organize), (grid_shown, extract), (written, check), argv=[make_pdf(sizes=SIZES, pages=5)])


def test_activating_a_tile_goes_back_to_reading_at_that_page(run_app, make_pdf):
    def activate(window) -> None:
        window.organize.emit("page-chosen", 3, True)

    def reading(window) -> bool:
        """the page view"""
        return window._stack.get_visible_child() is window._split

    def check(window) -> None:
        assert window.view.current_page == 3
        assert not window._actions["organize"].get_state().get_boolean()

    run_app((loaded, organize), (grid_shown, activate), (reading, check), argv=[make_pdf(pages=5)])


def test_insert_blank_goes_after_the_selected_pages(run_app, make_pdf):
    def insert(window) -> None:
        window.organize.select_pages([0, 1])
        window.activate_action("win.insert-blank", None)

    def inserted(window) -> bool:
        """the blank page"""
        return grid_shown(window) and len(window._page_sizes) == 4

    def check(window) -> None:
        assert widths(window) == [300, 400, 400, 500]
        assert window.organize.selected_pages() == [2]

    run_app((loaded, organize), (grid_shown, insert), (inserted, check), argv=[make_pdf(sizes=SIZES, pages=3)])


def test_combine_files_makes_a_new_document_to_put_in_order_and_save(run_app, make_pdf, tmp_path):
    first = make_pdf("first.pdf", pages=2, size=(300, 800))
    second = make_pdf("second.pdf", pages=1, size=(400, 800))
    joined = tmp_path / "joined.pdf"

    def combine(window) -> None:
        assert window._combine_button.get_visible()
        window.combine_files([str(first), str(second)])

    def combined(window) -> bool:
        """the combined pages in the grid"""
        return grid_shown(window) and len(window._page_sizes) == 3

    def check_and_save(window) -> None:
        assert widths(window) == [300, 300, 400]
        assert window._title.get_subtitle() == "• Combined.pdf"
        assert window.get_application().history.recent() == []  # not a file yet
        assert not (tmp_path / "Combined.pdf").exists()
        window.save_as(Gio.File.new_for_path(str(joined)))

    def saved(window) -> bool:
        """the new file"""
        return grid_shown(window) and not window._state.get("modified")

    def check_saved(window) -> None:
        assert window._title.get_subtitle() == "joined.pdf"
        assert window.get_application().history.recent()[0].path == str(joined)
        assert [round(page.rect.width) for page in pymupdf.open(joined).pages()] == [300, 300, 400]

    run_app(
        (lambda window: True, combine),
        (combined, check_and_save),
        (saved, check_saved),
    )

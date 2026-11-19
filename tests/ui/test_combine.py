# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Combine list: files in order, from any folders, before they are combined."""

import itertools
import os
import signal

import gi
import pymupdf

gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, Graphene, Gtk  # noqa: E402

from bluepencil.ui.combine_dialog import FileRow  # noqa: E402

from .test_organize import drop_target_of  # noqa: E402


def in_folder(tmp_path, folder: str, name: str) -> str:
    """A name inside a folder of its own, for make_pdf."""
    (tmp_path / folder).mkdir(exist_ok=True)
    return f"{folder}/{name}"


def picture(path) -> str:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 300, 200), False)
    pixmap.clear_with(160)
    pixmap.save(str(path))
    return str(path)


def all_read(window) -> bool:
    """every file in the list read"""
    dialog = window.combine_dialog
    return dialog is not None and bool(dialog.rows()) and not any(row.needs_reading for row in dialog.rows())


def titles(dialog) -> list[str]:
    return [row.get_title() for row in dialog.rows()]


def numbers(dialog) -> list[str]:
    return [row.number.get_label() for row in dialog.rows()]


def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from descendants(child)
        child = child.get_next_sibling()


def menu_items(row) -> dict[str, tuple[Gtk.Widget, str]]:
    """The items of the file's open menu, by label: each item, and the
    shortcut it shows."""
    items = {}
    for widget in descendants(row.menu_button.get_popover()):
        if type(widget).__name__ == "GtkModelButton":
            label, *keys = [text.get_label() for text in descendants(widget) if isinstance(text, Gtk.Label)]
            items[label] = (widget, "".join(keys))
    return items


def tint(row) -> int | None:
    """How opaque the row's own background is, out of 255, just inside its
    top edge: 0 when the list shows through untinted. None until drawn."""
    width, height = row.get_width(), row.get_height()
    snapshot = Gtk.Snapshot()
    Gtk.WidgetPaintable.new(row).snapshot(snapshot, width, height)
    node = snapshot.to_node()
    if node is None:
        return None
    texture = row.get_native().get_renderer().render_texture(node, Graphene.Rect().init(0, 0, width, height))
    downloader = Gdk.TextureDownloader.new(texture)
    downloader.set_format(Gdk.MemoryFormat.R8G8B8A8)
    pixels, stride = downloader.download_bytes()
    return pixels.get_data()[3 * stride + width // 2 * 4 + 3]


def widths(window) -> list[int]:
    return [round(width) for width, _height in window._page_sizes]


def combined(count: int):
    def condition(window) -> bool:
        return window.combine_dialog is None and window.view is not None and len(window._page_sizes) == count

    condition.__doc__ = f"the combined document of {count} pages"
    return condition


def test_files_from_several_folders_are_numbered_in_order_and_read(run_app, make_pdf, tmp_path):
    report = str(make_pdf(in_folder(tmp_path, "work", "report.pdf"), pages=2))
    photo = picture(tmp_path / "photo.png")
    notes = str(make_pdf(in_folder(tmp_path, "notes", "notes.pdf"), pages=1))

    def check(window) -> None:
        dialog = window.combine_dialog
        assert titles(dialog) == ["report.pdf", "photo.png", "notes.pdf"]
        assert numbers(dialog) == ["1", "2", "3"]
        assert [row.get_subtitle() for row in dialog.rows()] == [
            f"2 pages · {tmp_path / 'work'}",
            f"Picture · {tmp_path}",
            f"1 page · {tmp_path / 'notes'}",
        ]
        assert all(row.sheet.texture is not None for row in dialog.rows())
        assert dialog.summary.get_label() == "3 files, 4 pages"
        assert dialog.combine_button.get_sensitive()
        assert dialog.get_focus() is dialog.combine_button  # Enter combines

    run_app(lambda window: window.show_combine_list([report, photo, notes]), (all_read, check))


def test_more_files_can_be_added_from_another_folder(run_app, make_pdf, tmp_path):
    first = str(make_pdf(in_folder(tmp_path, "one", "first.pdf"), pages=1))
    second = str(make_pdf(in_folder(tmp_path, "two", "second.pdf"), pages=3))

    def add(window) -> None:
        window.combine_dialog.add_files([second])
        # Files dropped on the window while the list is open join it too.
        files = Gdk.FileList.new_from_array([Gio.File.new_for_path(first)])
        assert window._on_drop(None, files, 0, 0)

    def check(window) -> None:
        assert window.combine_dialog.paths() == [first, second, first]
        assert numbers(window.combine_dialog) == ["1", "2", "3"]
        assert window.combine_dialog.summary.get_label() == "3 files, 5 pages"

    run_app(lambda window: window.show_combine_list([first]), (all_read, add), (all_read, check))


def test_the_focused_file_moves_with_alt_and_the_arrow_keys_and_delete_removes_it(run_app, make_pdf, monkeypatch):
    paths = [str(make_pdf(f"{name}.pdf", pages=1)) for name in ("a", "b", "c")]
    said: list[str] = []
    monkeypatch.setattr(FileRow, "announce", lambda _row, message, _priority: said.append(message))

    def press(window, key: int, state: Gdk.ModifierType = Gdk.ModifierType.ALT_MASK) -> bool:
        return window.combine_dialog._on_key_pressed(None, key, 0, state)

    def check(window) -> None:
        dialog = window.combine_dialog
        dialog.rows()[0].grab_focus()
        assert press(window, Gdk.KEY_Down)
        assert titles(dialog) == ["b.pdf", "a.pdf", "c.pdf"]
        assert numbers(dialog) == ["1", "2", "3"]
        assert dialog.get_focus() is dialog.rows()[1]  # the moved file keeps the focus
        assert said == ["Moved to position 2 of 3"]  # for screen readers
        assert press(window, Gdk.KEY_Down)
        assert press(window, Gdk.KEY_Down)  # already last: nothing moves
        assert titles(dialog) == ["b.pdf", "c.pdf", "a.pdf"]
        assert len(said) == 2
        # From one of its buttons too, which keeps the focus.
        dialog.rows()[2].menu_button.grab_focus()
        assert press(window, Gdk.KEY_Up)
        assert titles(dialog) == ["b.pdf", "a.pdf", "c.pdf"]
        assert dialog.get_focus().is_ancestor(dialog.rows()[1].menu_button)
        assert press(window, Gdk.KEY_Delete, Gdk.ModifierType(0))
        assert titles(dialog) == ["b.pdf", "c.pdf"]
        assert numbers(dialog) == ["1", "2"]
        assert dialog._focused_row() is dialog.rows()[1]  # the next file

    run_app(lambda window: window.show_combine_list(paths), (all_read, check))


def test_each_file_has_a_menu_that_moves_it_and_shows_the_keys(run_app, make_pdf):
    paths = [str(make_pdf(f"{name}.pdf", pages=1)) for name in ("a", "b", "c")]
    state = {}

    def open_first(window) -> None:
        state["row"] = row = window.combine_dialog.rows()[0]
        assert row.menu_button.get_tooltip_text() == "Move"
        row.menu_button.popup()

    def menu_open(_window) -> bool:
        """the file's menu to open"""
        return state["row"].menu_button.get_popover().get_mapped()

    def move_to_bottom(window) -> None:
        dialog, row = window.combine_dialog, state["row"]
        items = menu_items(row)
        assert {label: (keys, item.get_sensitive()) for label, (item, keys) in items.items()} == {
            "Move Up": ("Alt+Up", False),  # already first
            "Move Down": ("Alt+Down", True),
            "Move to Top": ("Alt+Home", False),
            "Move to Bottom": ("Alt+End", True),
        }
        items["Move to Bottom"][0].emit("clicked")
        assert titles(dialog) == ["b.pdf", "c.pdf", "a.pdf"]
        assert numbers(dialog) == ["1", "2", "3"]
        assert not row.menu_button.get_popover().get_visible()
        assert dialog.get_focus().is_ancestor(row.menu_button)  # ready to move it again
        row.menu_button.popup()

    def move_up(window) -> None:
        dialog = window.combine_dialog
        items = menu_items(state["row"])
        assert [label for label, (item, _keys) in items.items() if item.get_sensitive()] == ["Move Up", "Move to Top"]
        items["Move Up"][0].emit("clicked")
        assert titles(dialog) == ["b.pdf", "a.pdf", "c.pdf"]
        for row in dialog.rows()[1:]:
            dialog.remove(row)
        assert not dialog.rows()[0].menu_button.get_sensitive()  # a single file goes nowhere

    run_app(
        lambda window: window.show_combine_list(paths),
        (all_read, open_first),
        (menu_open, move_to_bottom),
        (menu_open, move_up),
    )


def test_every_shortcut_in_the_menu_does_what_its_item_does(run_app, make_pdf):
    paths = [str(make_pdf(f"{name}.pdf", pages=1)) for name in "abcde"]
    # "c" moved from the middle.
    expected = {
        "row.move-up": "acbde",
        "row.move-down": "abdce",
        "row.move-to-top": "cabde",
        "row.move-to-bottom": "abdec",
    }

    def order(dialog) -> str:
        return "".join(title.removesuffix(".pdf") for title in titles(dialog))

    def middle(dialog) -> FileRow:
        """File "c", back in the middle and focused."""
        row = next(row for row in dialog.rows() if row.get_title() == "c.pdf")
        dialog.move(row.get_index(), 2 if row.get_index() > 2 else 3)
        assert order(dialog) == "abcde"
        row.grab_focus()
        return row

    def check(window) -> None:
        dialog = window.combine_dialog
        menu = dialog.rows()[0].menu_button.get_menu_model()
        shown = {}
        for section in range(menu.get_n_items()):
            items = menu.get_item_link(section, Gio.MENU_LINK_SECTION)
            for index in range(items.get_n_items()):
                action = items.get_item_attribute_value(index, "action", None).get_string()
                shown[action] = items.get_item_attribute_value(index, "accel", None).get_string()
        assert set(shown) == set(expected)
        for action, accel in shown.items():
            middle(dialog).activate_action(action, None)
            assert order(dialog) == expected[action], action
            middle(dialog)
            _ok, keyval, modifiers = Gtk.accelerator_parse(accel)
            assert dialog._on_key_pressed(None, keyval, 0, modifiers)
            assert order(dialog) == expected[action], accel

    run_app(lambda window: window.show_combine_list(paths), (all_read, check))


def test_the_pointer_shows_that_files_can_be_dragged_by_any_part(run_app, make_pdf):
    def check(window) -> None:
        row = window.combine_dialog.rows()[0]
        assert row.get_cursor().get_name() == "grab"  # an open hand
        for button in (row.unlock_button, row.menu_button, row.remove_button):
            assert button.get_cursor().get_name() == "default"  # clicked, not dragged
        drag = next(controller for controller in row.observe_controllers() if isinstance(controller, Gtk.DragSource))
        drag.emit("begin", None)  # pressed
        assert row.get_cursor().get_name() == "grabbing"
        drag.emit("end", None)  # let go
        assert row.get_cursor().get_name() == "grab"

    run_app(lambda window: window.show_combine_list([str(make_pdf())]), (all_read, check))


def test_the_file_the_keys_would_move_is_tinted(run_app, make_pdf):
    paths = [str(make_pdf(f"{name}.pdf", pages=1)) for name in ("a", "b")]
    clearly = 32  # out of 255; the tint fades in to a quarter

    def drawn(window) -> bool:
        """the list read and drawn, no file tinted"""
        return all_read(window) and all(tint(row) == 0 for row in window.combine_dialog.rows())

    def click_first(window) -> None:
        window.combine_dialog.rows()[0].grab_focus()  # as clicking it does

    def first_tinted(window) -> bool:
        """the first file to be tinted"""
        return (tint(window.combine_dialog.rows()[0]) or 0) > clearly

    def open_second_menu(window) -> None:
        window.combine_dialog.rows()[1].menu_button.popup()

    def tint_moved(window) -> bool:
        """the tint to move to the file whose menu is open"""
        first, second = window.combine_dialog.rows()
        return tint(first) == 0 and (tint(second) or 0) > clearly

    def click_combine_button(window) -> None:
        window.combine_dialog.combine_button.grab_focus()

    def none_tinted(window) -> bool:
        """no file tinted once the focus leaves the list: the keys move none"""
        return all(tint(row) == 0 for row in window.combine_dialog.rows())

    run_app(
        lambda window: window.show_combine_list(paths),
        (drawn, click_first),
        (first_tinted, open_second_menu),
        (tint_moved, click_combine_button),
        (none_tinted, lambda _window: None),
    )


def test_dragged_files_and_dropped_files_land_where_they_are_dropped(run_app, make_pdf, tmp_path):
    paths = [str(make_pdf(f"{name}.pdf", pages=1)) for name in ("a", "b", "c")]
    extra = str(make_pdf(in_folder(tmp_path, "elsewhere", "extra.pdf"), pages=2))

    def laid_out(window) -> bool:
        """the list laid out, in its current order"""
        if not all_read(window):
            return False
        dialog = window.combine_dialog
        tops = [row.compute_bounds(dialog.list)[1].get_y() for row in dialog.rows()]
        return dialog.rows()[-1].get_height() > 0 and all(a < b for a, b in itertools.pairwise(tops))

    def upper_half_of(dialog, index: int) -> float:
        _ok, bounds = dialog.rows()[index].compute_bounds(dialog.stack)
        return bounds.get_y() + bounds.get_height() * 0.25

    def drag(window) -> None:
        dialog = window.combine_dialog
        # File "a" dragged onto the upper half of "c": it goes just before it.
        assert dialog._on_drop(drop_target_of(dialog.stack), f"{dialog._drag_tag}0", 10, upper_half_of(dialog, 2))
        assert titles(dialog) == ["b.pdf", "a.pdf", "c.pdf"]

    def drop_file(window) -> None:
        dialog = window.combine_dialog
        target = drop_target_of(dialog.stack)
        # A file from the Files app, dropped on the upper half of "a".
        files = Gdk.FileList.new_from_array([Gio.File.new_for_path(extra)])
        assert dialog._on_drop(target, files, 10, upper_half_of(dialog, 1))
        assert titles(dialog) == ["b.pdf", "extra.pdf", "a.pdf", "c.pdf"]
        assert numbers(dialog) == ["1", "2", "3", "4"]
        # Pages dragged from another window are not files of this list.
        assert not dialog._on_drop(target, "bluepencil-page:0", 10, upper_half_of(dialog, 0))

    def check_end(window) -> None:
        dialog = window.combine_dialog
        _ok, last = dialog.rows()[-1].compute_bounds(dialog.stack)
        assert dialog.drop_position(dialog.stack, last.get_y() + last.get_height() * 0.75) == 4

    run_app(
        lambda window: window.show_combine_list(paths),
        (laid_out, drag),
        (laid_out, drop_file),
        (laid_out, check_end),
    )


def test_combine_uses_the_order_of_the_list(run_app, make_pdf):
    narrow = str(make_pdf("narrow.pdf", pages=2, size=(300, 800)))
    wide = str(make_pdf("wide.pdf", pages=1, size=(500, 800)))

    def arrange_and_combine(window) -> None:
        dialog = window.combine_dialog
        dialog.move(1, 0)
        dialog.combine_button.emit("clicked")

    def check(window) -> None:
        assert widths(window) == [500, 300, 300]
        assert window._title.get_subtitle() == "• Combined.pdf"

    run_app(
        lambda window: window.show_combine_list([narrow, wide]),
        (all_read, arrange_and_combine),
        (combined(3), check),
    )


def test_combine_pressed_early_waits_for_the_files_to_be_read(run_app, make_pdf):
    paths = [str(make_pdf("a.pdf", pages=2)), str(make_pdf("b.pdf", pages=1))]

    def open_and_combine(window) -> None:
        dialog = window.show_combine_list(paths)
        assert any(row.needs_reading for row in dialog.rows())
        dialog.combine_button.emit("clicked")

    run_app(open_and_combine, (combined(3), lambda _window: None))


def test_a_locked_file_is_unlocked_in_the_list(run_app, make_pdf):
    plain = str(make_pdf("plain.pdf", pages=1))
    locked = str(make_pdf("locked.pdf", pages=2, password="secret"))

    def locked_row(window):
        return window.combine_dialog.rows()[1]

    def check_locked(window) -> None:
        dialog, row = window.combine_dialog, locked_row(window)
        assert row.problem == "needs-password" and row.unlock_button.get_visible()
        assert row.get_subtitle().startswith("Locked with a password")
        assert not dialog.combine_button.get_sensitive()
        assert dialog.summary.get_label() == "1 file can’t be combined as it is."
        dialog.unlock(row, "guess")

    def check_wrong(window) -> None:
        dialog, row = window.combine_dialog, locked_row(window)
        assert row.problem == "wrong-password" and row.unlock_button.get_visible()
        dialog.unlock(row, "secret")

    def check_unlocked_and_combine(window) -> None:
        dialog, row = window.combine_dialog, locked_row(window)
        assert row.problem is None and row.pages == 2 and not row.unlock_button.get_visible()
        assert dialog.summary.get_label() == "2 files, 3 pages. The new PDF won’t have a password."
        dialog.combine_button.emit("clicked")

    run_app(
        lambda window: window.show_combine_list([plain, locked]),
        (all_read, check_locked),
        (all_read, check_wrong),
        (all_read, check_unlocked_and_combine),
        (combined(3), lambda _window: None),
    )


def test_a_file_that_cannot_be_combined_must_go_first(run_app, make_pdf, tmp_path):
    good = str(make_pdf("good.pdf", pages=1))
    (tmp_path / "notes.txt").write_text("not a document")
    bad = str(tmp_path / "notes.txt")

    def check(window) -> None:
        dialog = window.combine_dialog
        row = dialog.rows()[1]
        assert row.problem == "unsupported-file" and row.warning.get_visible()
        assert not row.unlock_button.get_visible()
        assert not dialog.combine_button.get_sensitive()
        row.remove_button.emit("clicked")
        assert dialog.paths() == [good]
        assert dialog.combine_button.get_sensitive()
        assert dialog.summary.get_label() == "1 file, 1 page"

    run_app(lambda window: window.show_combine_list([good, bad]), (all_read, check))


def test_removing_every_file_leaves_the_empty_page(run_app, make_pdf):
    def check(window) -> None:
        dialog = window.combine_dialog
        dialog.rows()[0].remove_button.emit("clicked")
        assert dialog.stack.get_visible_child_name() == "empty"
        assert not dialog.combine_button.get_sensitive()
        assert not dialog.summary.get_visible()

    run_app(lambda window: window.show_combine_list([str(make_pdf())]), (all_read, check))


def test_a_file_that_stops_the_engine_is_pointed_out_and_the_rest_are_read(run_app, make_pdf):
    paths = [str(make_pdf("a.pdf", pages=1)), str(make_pdf("b.pdf", pages=2))]

    def open_and_crash(window) -> None:
        dialog = window.show_combine_list(paths)
        assert dialog._reading is dialog.rows()[0]
        os.kill(dialog._engine.pid, signal.SIGKILL)

    def check(window) -> None:
        dialog = window.combine_dialog
        assert dialog.rows()[0].problem == "engine-failed"
        assert dialog.rows()[1].pages == 2

    run_app(open_and_crash, (all_read, check))


def test_dropping_several_files_on_the_start_page_opens_the_list(run_app, make_pdf):
    paths = [str(make_pdf("a.pdf", pages=1)), str(make_pdf("b.pdf", pages=1))]

    def drop(window) -> None:
        files = Gdk.FileList.new_from_array([Gio.File.new_for_path(path) for path in paths])
        assert window._on_drop(None, files, 0, 0)

    def check(window) -> None:
        assert window.combine_dialog.paths() == paths
        assert window.current_file is None  # nothing opened on its own

    run_app(drop, (all_read, check))


def test_closing_the_list_stops_its_engine(run_app, make_pdf):
    def close(window) -> None:
        dialog = window.combine_dialog
        engine = dialog._engine
        dialog.close()
        assert window.combine_dialog is None
        assert not engine.running

    run_app(lambda window: window.show_combine_list([str(make_pdf())]), (all_read, close))


def test_list_widgets_are_reachable_by_keyboard(run_app, make_pdf):
    def check(window) -> None:
        row = window.combine_dialog.rows()[0]
        assert row.get_focusable()
        assert isinstance(row.remove_button, Gtk.Button) and row.remove_button.get_tooltip_text() == "Remove"

    run_app(lambda window: window.show_combine_list([str(make_pdf())]), (all_read, check))

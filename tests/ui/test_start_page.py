# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The start page: its buttons, its recent files, and returning to where the
reader left a file."""

import gi
import pytest

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from bluepencil.history import History  # noqa: E402
from bluepencil.ui.document_view import MARGIN  # noqa: E402

from .helpers import drawn_top, loaded  # noqa: E402


def remember(*paths) -> None:
    """Record `paths` as opened, oldest first, as an earlier session would."""
    history = History()
    for path in paths:
        history.opened(str(path))
    history.save()


def start_page_shown(window) -> bool:
    """the start page"""
    return window._stack.get_visible_child() is window._status and window._status.get_title() == "Open a PDF"


def recent_paths(window) -> list[str]:
    return [entry.path for entry in window.get_application().history.recent()]


def shown_titles(window) -> list[str]:
    return [row.get_title() for _path, row in window._recent_rows]


def find_button(widget: Gtk.Widget, tooltip: str) -> Gtk.Button:
    """The button inside `widget` with this tooltip."""
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Button) and child.get_tooltip_text() == tooltip:
            return child
        try:
            return find_button(child, tooltip)
        except LookupError:
            child = child.get_next_sibling()
    raise LookupError(tooltip)


def shows_page(index: int):
    def condition(window) -> bool:
        return window.view is not None and window.view.pages[index].texture is not None

    condition.__doc__ = f"page {index + 1} to be drawn"
    return condition


def test_the_start_page_lists_recent_files_newest_first(run_app, make_pdf):
    older, newer = make_pdf("older.pdf"), make_pdf("Q1 & Q2 <draft>.pdf")
    remember(older, newer)

    def check(window) -> None:
        assert window._recent_group.get_visible()
        assert shown_titles(window) == ["Q1 & Q2 <draft>.pdf", "older.pdf"]
        assert window._recent_rows[0][1].get_subtitle() == str(newer.parent)

    run_app((start_page_shown, check))


def test_the_start_buttons_are_equally_wide(run_app):
    def laid_out(window) -> bool:
        """the buttons laid out"""
        return start_page_shown(window) and window._combine_button.get_width() > 0

    def check(window) -> None:
        open_button, combine = window._open_button, window._combine_button
        assert open_button.get_width() == combine.get_width()
        # As wide as the wider button needs, not stretched across the page.
        widest = max(button.measure(Gtk.Orientation.HORIZONTAL, -1)[1] for button in (open_button, combine))
        assert combine.get_parent().get_width() == widest

    run_app((laid_out, check))


def test_without_recent_files_the_list_is_hidden(run_app):
    def check(window) -> None:
        assert not window._recent_group.get_visible()

    run_app((start_page_shown, check))


def test_choosing_a_recent_file_opens_it(run_app, make_pdf):
    first, second = make_pdf("first.pdf"), make_pdf("second.pdf")
    remember(first, second)

    def choose_first(window) -> None:
        assert shown_titles(window) == ["second.pdf", "first.pdf"]
        window._recent_rows[1][1].activate()

    def check(window) -> None:
        assert window.current_file.get_path() == str(first)
        assert recent_paths(window) == [str(first), str(second)]

    run_app((start_page_shown, choose_first), (loaded, check))


def test_opening_a_file_puts_it_at_the_top_of_the_list(run_app, make_pdf):
    earlier, path = make_pdf("earlier.pdf"), make_pdf("today.pdf")
    remember(earlier)

    def check(window) -> None:
        assert recent_paths(window) == [str(path), str(earlier)]

    run_app((loaded, check), argv=[path])


def test_a_file_can_be_removed_from_the_list(run_app, make_pdf):
    keep, drop = make_pdf("keep.pdf"), make_pdf("drop.pdf")
    remember(keep, drop)

    def remove_drop(window) -> None:
        path, row = window._recent_rows[0]
        assert path == str(drop)
        find_button(row, "Remove From List").emit("clicked")

    def check(window) -> None:
        assert shown_titles(window) == ["keep.pdf"]
        assert recent_paths(window) == [str(keep)]

    run_app((start_page_shown, remove_drop), check)
    # The change is written when the app quits.
    assert [entry.path for entry in History().recent()] == [str(keep)]


def test_clear_list_empties_and_hides_it(run_app, make_pdf):
    remember(make_pdf("a.pdf"), make_pdf("b.pdf"))

    def clear(window) -> None:
        window._recent_group.get_header_suffix().emit("clicked")

    def check(window) -> None:
        assert not window._recent_group.get_visible()
        assert recent_paths(window) == []

    run_app((start_page_shown, clear), check)


def test_a_recent_file_that_is_gone_leaves_the_list(run_app, make_pdf):
    kept, gone = make_pdf("kept.pdf"), make_pdf("gone.pdf")
    remember(kept, gone)
    gone.unlink()

    def choose_gone(window) -> None:
        window._recent_rows[0][1].activate()

    def error_shown(window) -> bool:
        """the error page"""
        return window._status.get_title() == "Can’t Open “gone.pdf”"

    def check(window) -> None:
        assert recent_paths(window) == [str(kept)]
        assert not window._recent_group.get_visible()  # not on an error page

    run_app((start_page_shown, choose_gone), (error_shown, check))


def test_reopening_a_file_returns_to_the_same_page_and_zoom(run_app, make_pdf):
    path = make_pdf(pages=60)

    def leave_at_page_38(window) -> None:
        window.view.set_zoom(1.5)
        window.view.go_to_page(37)

    run_app((loaded, leave_at_page_38), argv=[path])

    def check(window) -> None:
        view = window.view
        assert view.current_page == 37
        assert view.zoom == pytest.approx(1.5)
        assert view.fit_mode is None
        assert drawn_top(view, 37) == pytest.approx(MARGIN, abs=2)
        assert window._page_entry.get_text() == "38"
        assert window._zoom_button.get_label() == "150%"
        window.activate_action("win.toggle-sidebar", None)

    def thumbnail_selected(window) -> None:
        assert window.sidebar.selected == 37

    run_app((shows_page(37), check), thumbnail_selected, argv=[path])


def test_fit_page_is_remembered(run_app, make_pdf):
    path = make_pdf(pages=4)
    run_app((loaded, lambda window: window.activate_action("win.zoom-fit-page", None)), argv=[path])

    def check(window) -> None:
        assert window.view.fit_mode == "page"

    run_app((loaded, check), argv=[path])

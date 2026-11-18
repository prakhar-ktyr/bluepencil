# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recent files and remembered positions, without a window."""

import json
import stat

from bluepencil.history import MAX_FILES, History, default_path


def saved(history: History) -> list[str]:
    """Paths in the file on disk, after writing what is waiting."""
    history.save()
    return [entry["path"] for entry in json.loads(history.path.read_text())["files"]]


def test_the_file_lives_in_the_state_folder(private_state):
    assert default_path() == private_state / "bluepencil" / "history.json"
    assert History().path == default_path()


def test_recent_files_are_newest_first_and_never_repeat():
    history = History()
    for path in ("/a.pdf", "/b.pdf", "/c.pdf", "/a.pdf"):
        history.opened(path)
    assert [entry.path for entry in history.recent()] == ["/a.pdf", "/c.pdf", "/b.pdf"]
    assert saved(history) == ["/a.pdf", "/c.pdf", "/b.pdf"]


def test_positions_survive_a_restart():
    history = History()
    history.opened("/report.pdf")
    history.remember_position("/report.pdf", page=41, zoom=1.5, fit=None)
    history.opened("/other.pdf")
    history.save()

    entry = History().lookup("/report.pdf")
    assert entry is not None
    assert (entry.page, entry.zoom, entry.fit) == (41, 1.5, None)
    assert entry.opened > 0


def test_a_new_file_starts_at_the_top_of_its_first_page_fitted_to_the_width():
    history = History()
    history.opened("/new.pdf")
    entry = history.lookup("/new.pdf")
    assert entry is not None
    assert (entry.page, entry.zoom, entry.fit) == (0, 1.0, "width")


def test_positions_are_kept_only_for_files_in_the_list():
    history = History()
    history.remember_position("/never-opened.pdf", page=3, zoom=1.0, fit="width")
    assert history.lookup("/never-opened.pdf") is None
    assert not history.path.exists()


def test_the_oldest_files_are_forgotten_beyond_the_limit():
    history = History()
    for number in range(MAX_FILES + 5):
        history.opened(f"/file-{number}.pdf")
    paths = saved(history)
    assert len(paths) == MAX_FILES
    assert paths[0] == f"/file-{MAX_FILES + 4}.pdf"
    assert "/file-4.pdf" not in paths


def test_forget_and_clear_announce_the_change():
    history = History()
    changes = []
    history.connect("changed", lambda _history: changes.append(True))
    history.opened("/a.pdf")
    history.opened("/b.pdf")
    history.forget("/a.pdf")
    assert saved(history) == ["/b.pdf"]
    history.clear()
    assert saved(history) == []
    assert len(changes) == 4


def test_only_the_owner_can_read_the_file():
    history = History()
    history.opened("/private/tax-return.pdf")
    history.save()
    assert stat.S_IMODE(history.path.stat().st_mode) == 0o600


def test_nothing_is_recorded_when_the_desktop_turns_file_history_off():
    history = History(allowed=lambda: False)
    history.opened("/a.pdf")
    assert history.recent() == []
    history.save()
    assert not history.path.exists()


def test_a_damaged_file_is_ignored_and_replaced(private_state):
    path = default_path()
    path.parent.mkdir(parents=True)
    path.write_text("{ not json")
    history = History()
    assert history.recent() == []
    history.opened("/a.pdf")
    assert saved(history) == ["/a.pdf"]


def test_wrong_entries_are_skipped(private_state):
    path = default_path()
    path.parent.mkdir(parents=True)
    good = {"path": "/good.pdf", "opened": 5, "page": 2, "zoom": 1.25, "fit": None}
    wrong = [
        "not an entry",
        {**good, "path": "relative.pdf"},
        {**good, "page": -1},
        {**good, "page": True},
        {**good, "zoom": 0},
        {**good, "zoom": "big"},
        {**good, "fit": "sideways"},
        {**good, "opened": None},
    ]
    path.write_text(json.dumps({"format": 1, "files": [*wrong, good, {**good, "page": 9}]}))
    entries = History().recent()
    assert [(entry.path, entry.page) for entry in entries] == [("/good.pdf", 2)]


def test_a_file_from_an_unknown_format_is_not_read(private_state):
    path = default_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"format": 99, "files": [{"path": "/a.pdf"}]}))
    assert History().recent() == []

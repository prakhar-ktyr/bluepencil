# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Splitting a document into several new files."""

import pymupdf

from bluepencil.ui.split_dialog import SplitDialog

from .helpers import loaded
from .test_editing import settled


def test_the_dialog_accepts_only_ranges_that_exist(run_app):
    def check(_window) -> None:
        dialog = SplitDialog(10)
        assert dialog.groups() == [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9]]  # every 2 pages to start with
        dialog.ranges.set_text("1-3, 4-")
        assert dialog.ranges_choice.get_active()  # typing chooses ranges
        assert dialog.groups() == [[0, 1, 2], list(range(3, 10))]
        assert dialog.get_response_enabled("split")
        assert dialog.hint.get_label() == "2 new files."
        dialog.ranges.set_text("4-12")
        assert dialog.groups() is None
        assert not dialog.get_response_enabled("split")
        assert dialog.hint.get_label() == "Pages go from 1 to 10."

    run_app((lambda window: True, check))


def test_split_writes_the_parts_next_to_each_other(run_app, make_pdf, tmp_path):
    folder = tmp_path / "parts"
    folder.mkdir()

    def split(window) -> None:
        window.split_into([[0, 1], [2], [3, 4]], str(folder))

    def written(window) -> bool:
        """the new files"""
        return settled(window) and len(list(folder.iterdir())) == 3

    def check(window) -> None:
        names = sorted(path.name for path in folder.iterdir())
        assert names == ["sample, part 1.pdf", "sample, part 2.pdf", "sample, part 3.pdf"]
        assert [pymupdf.open(folder / name).page_count for name in names] == [2, 1, 2]
        assert not window._state.get("modified")

    run_app((loaded, split), (written, check), argv=[make_pdf(pages=5)])

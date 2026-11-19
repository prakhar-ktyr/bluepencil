# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Finding unsaved changes left behind by a crash."""

import json
import subprocess
import sys
from pathlib import Path

from bluepencil.core.places import MANIFEST, snapshots_root
from bluepencil.recovery import discard, find_recoverable

from .crash import crash_after_rotating


def test_a_crash_leaves_changes_that_can_be_recovered(make_pdf):
    path = make_pdf()
    history = crash_after_rotating(path)
    folder = Path(history["folder"])
    assert folder.parent == snapshots_root()

    found = find_recoverable()
    assert [(item.path, item.name, item.untitled) for item in found] == [(str(path), "sample.pdf", False)]
    assert found[0].history["files"] == history["files"]
    assert all(Path(name).exists() for name in found[0].history["files"])

    discard(found[0])
    assert not folder.exists()
    assert find_recoverable() == []


def manifest_folder(name: str, **fields) -> Path:
    folder = snapshots_root() / name
    folder.mkdir(parents=True)
    manifest = {
        "format": 1,
        "path": "/somewhere/file.pdf",
        "untitled": False,
        "files": ["a.pdf", "b.pdf"],
        "position": 1,
        "saved_position": 0,
        "engine": 999_999_999,
        "interface": 999_999_999,
        **fields,
    }
    (folder / MANIFEST).write_text(json.dumps(manifest))
    return folder


def test_folders_still_in_use_are_left_alone():
    # A process that looks like a running Bluepencil.
    with subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "bluepencil"]) as running:
        try:
            folder = manifest_folder("edits-running", engine=running.pid)
            assert find_recoverable() == []
            assert folder.exists()
        finally:
            running.kill()


def test_folders_with_nothing_unsaved_are_cleared_away():
    folder = manifest_folder("edits-saved", position=3, saved_position=3)
    assert find_recoverable() == []
    assert not folder.exists()


def test_unreadable_folders_are_skipped_and_kept():
    folder = snapshots_root() / "edits-broken"
    folder.mkdir(parents=True)
    (folder / MANIFEST).write_text("{ not json")
    sneaky = manifest_folder("edits-sneaky", files=["../../outside.pdf"])
    assert find_recoverable() == []
    assert folder.exists() and sneaky.exists()

# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""An open document, its history of edits, and saving (plan, D4 and D5).

After each edit the whole document is written to a snapshot file. Undo and
redo reopen an earlier or a later snapshot. The snapshots also let a new
engine process carry on where a crashed one stopped, edits and all.

Saving writes a complete new file next to the original, reopens it to check
it, and only then puts it in the original's place.
"""

import errno
import json
import os
import secrets
import shutil
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path

import pymupdf

from . import pages
from .document import KEEP_ENCRYPTION, describe, open_document
from .places import MANIFEST, snapshots_root

#: Steps that can be undone, and the disk space their snapshots may take;
#: the oldest steps go first, but never below MIN_STEPS.
MAX_STEPS = 30
MAX_BYTES = 1024**3
MIN_STEPS = 5

Change = Callable[[pymupdf.Document], list[int]]


class SaveError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


#: Codes for SaveError.
NO_PERMISSION = "no-permission"
DISK_FULL = "disk-full"
READ_ONLY = "read-only"
WRITE_FAILED = "write-failed"
CHECK_FAILED = "check-failed"


class Session:
    """One open document and its history."""

    def __init__(self, path: str, password: str | None = None) -> None:
        #: The file Save writes to.
        self.path = path
        self.password = password
        self.document = open_document(path, password)
        #: Snapshot files, oldest first. The document matches the one at
        #: `position`; before the first edit there are none, and position is -1.
        self.folder: Path | None = None
        self.snapshots: list[Path] = []
        self.position = -1
        #: The snapshot that matches the file on disk.
        self.saved_position = -1
        #: A new document that has never been saved: Save needs a place first.
        self.untitled = False

    @classmethod
    def combine(cls, paths: list[str], target: str, passwords: dict[str, str] | None = None) -> "Session":
        """A new document made of these PDFs and pictures, in this order.

        It has no file yet; `target` is only the suggested place to save it.
        `passwords` unlocks locked PDFs, by path.
        """
        document = pymupdf.open()
        try:
            pages.insert_files(document, paths, 0, passwords)
        except Exception:
            document.close()
            raise
        session = cls.__new__(cls)
        session.path, session.password, session.document = target, None, document
        session.folder, session.snapshots, session.position, session.saved_position = None, [], -1, -1
        session.untitled = True
        # The first snapshot holds the new document, so that undo stops there
        # and a crash loses nothing; it is not on disk, so it counts as unsaved.
        session._snapshot()
        session._write_manifest()
        return session

    @classmethod
    def resume(
        cls,
        path: str,
        password: str | None,
        *,
        folder: str,
        files: list[str],
        position: int,
        saved_position: int,
        untitled: bool = False,
    ) -> "Session":
        """Carry on from the snapshots of an engine process that stopped."""
        snapshots = [Path(file) for file in files]
        usable = 0 <= position < len(snapshots) and all(
            snapshot.is_file() and snapshot.parent == Path(folder) for snapshot in snapshots
        )
        session = cls.__new__(cls)
        session.path = path
        session.password = password
        session.untitled = untitled
        if usable:
            session.document = open_document(str(snapshots[position]), password)
            session.folder, session.snapshots = Path(folder), snapshots
            session.position, session.saved_position = position, saved_position
            session._write_manifest()  # this engine looks after them now
        else:
            # Without its snapshots, the history is gone: start again from the file.
            session.document = open_document(path, password)
            session.folder, session.snapshots, session.position, session.saved_position = None, [], -1, -1
        return session

    # History

    @property
    def can_undo(self) -> bool:
        return self.position > 0

    @property
    def can_redo(self) -> bool:
        return 0 <= self.position < len(self.snapshots) - 1

    @property
    def modified(self) -> bool:
        """True when the document differs from the file on disk."""
        return self.position != self.saved_position

    def edit(self, change: Change) -> list[int]:
        """Make `change` to the document as one step that can be undone.

        Returns the pages `change` says to select. If it fails, the document
        is put back as it was.
        """
        if self.position < 0:
            self.saved_position = 0
            self._snapshot()  # the document before its first edit
        try:
            selection = change(self.document)
        except Exception:
            self._load(self.position)
            raise
        for later in self.snapshots[self.position + 1 :]:
            later.unlink(missing_ok=True)
        del self.snapshots[self.position + 1 :]
        if self.saved_position > self.position:
            self.saved_position = -1  # the saved state was undone and is now gone
        self._snapshot()
        self._forget_old_steps()
        self._write_manifest()
        return selection

    def undo(self) -> None:
        if self.can_undo:
            self._load(self.position - 1)
            self._write_manifest()

    def redo(self) -> None:
        if self.can_redo:
            self._load(self.position + 1)
            self._write_manifest()

    # Saving

    def save(self, target: str | None = None) -> None:
        """Write the document to `target`, or to its own file (plan, D5)."""
        destination = Path(target or self.path)
        final = destination.resolve()  # through a link, to the real file
        temporary = final.with_name(f".{final.name}.{secrets.token_hex(4)}.part")
        try:
            # Made here first, so that a folder that cannot be written to is
            # reported as such: the PDF library's own errors give no reason.
            os.close(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
            self.document.save(temporary, garbage=1, deflate=True, encryption=KEEP_ENCRYPTION)
            _flush_to_disk(temporary)
            self._check(temporary)
            if final.exists():
                temporary.chmod(stat.S_IMODE(final.stat().st_mode))
            temporary.replace(final)
            _flush_to_disk(final.parent)
        except SaveError:
            raise
        except OSError as error:
            raise SaveError(_save_error_code(error), str(error)) from error
        except Exception as error:  # the PDF library has errors of its own
            raise SaveError(_library_error_code(str(error)), f"{type(error).__name__}: {error}") from error
        finally:
            temporary.unlink(missing_ok=True)
        self.path = str(destination)
        self.saved_position = self.position
        self.untitled = False
        self._write_manifest()

    def _check(self, path: Path) -> None:
        """Reopen a written file to make sure it is complete."""
        try:
            check = open_document(str(path), self.password)
        except Exception as error:
            raise SaveError(CHECK_FAILED, str(error)) from error
        try:
            if check.page_count != self.document.page_count:
                raise SaveError(CHECK_FAILED, f"{check.page_count} pages instead of {self.document.page_count}")
        finally:
            check.close()

    # State for the interface

    def state(self) -> dict:
        """The document's layout and history, as the interface needs them."""
        return {
            **describe(self.document),
            "can_undo": self.can_undo,
            "can_redo": self.can_redo,
            "modified": self.modified,
            "untitled": self.untitled,
            "history": None
            if self.folder is None
            else {
                "folder": str(self.folder),
                "files": [str(snapshot) for snapshot in self.snapshots],
                "position": self.position,
                "saved_position": self.saved_position,
                "untitled": self.untitled,
            },
        }

    def close(self, keep_snapshots: bool = False) -> None:
        """Close the document and delete its snapshots, or keep them so that
        unsaved changes can be recovered."""
        self.document.close()
        if self.folder is not None and not keep_snapshots:
            shutil.rmtree(self.folder, ignore_errors=True)
            self.folder = None

    def _write_manifest(self) -> None:
        """Say in the snapshot folder what it holds, for recovery."""
        if self.folder is None:
            return
        manifest = {
            "format": 1,
            "path": self.path,
            "untitled": self.untitled,
            "files": [snapshot.name for snapshot in self.snapshots],
            "position": self.position,
            "saved_position": self.saved_position,
            # While either process runs, the snapshots are in use.
            "engine": os.getpid(),
            "interface": os.getppid(),
        }
        temporary = self.folder / f"{MANIFEST}.tmp"
        temporary.write_text(json.dumps(manifest))
        temporary.replace(self.folder / MANIFEST)

    # Snapshots

    def _snapshot(self) -> None:
        if self.folder is None:
            root = snapshots_root()
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.folder = Path(tempfile.mkdtemp(prefix="edits-", dir=root))
        path = self.folder / f"{secrets.token_hex(6)}.pdf"
        # No clean-up: snapshots are written for speed and deleted on close.
        self.document.save(path, garbage=0, encryption=KEEP_ENCRYPTION)
        self.snapshots.append(path)
        self.position = len(self.snapshots) - 1

    def _load(self, position: int) -> None:
        document = open_document(str(self.snapshots[position]), self.password)
        self.document.close()
        self.document = document
        self.position = position

    def _forget_old_steps(self) -> None:
        def total() -> int:
            return sum(snapshot.stat().st_size for snapshot in self.snapshots if snapshot.exists())

        while self.position > MIN_STEPS and (self.position > MAX_STEPS or total() > MAX_BYTES):
            self.snapshots.pop(0).unlink(missing_ok=True)
            self.position -= 1
            self.saved_position -= 1  # below 0: the saved state is no longer in the history


def _flush_to_disk(path: Path) -> None:
    """Make sure a file, or a folder's list of files, is on the disk itself,
    so that a power cut right after saving cannot lose it."""
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _library_error_code(message: str) -> str:
    """A code for an error from the PDF library, which only gives a message."""
    for text, code in (
        (os.strerror(errno.ENOSPC), DISK_FULL),
        (os.strerror(errno.EDQUOT), DISK_FULL),
        (os.strerror(errno.EACCES), NO_PERMISSION),
        (os.strerror(errno.EROFS), READ_ONLY),
    ):
        if text in message:
            return code
    return WRITE_FAILED


def _save_error_code(error: OSError) -> str:
    if error.errno in (errno.EACCES, errno.EPERM):
        return NO_PERMISSION
    if error.errno in (errno.ENOSPC, errno.EDQUOT):
        return DISK_FULL
    if error.errno == errno.EROFS:
        return READ_ONLY
    return WRITE_FAILED

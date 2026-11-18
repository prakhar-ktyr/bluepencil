# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recent files, and where the reader left each one.

Kept in $XDG_STATE_HOME/bluepencil/history.json, normally
~/.local/state/bluepencil/history.json (plan, D7): it is the app's state, not
a setting and not a document. Only its owner can read the file, because the
names of someone's documents are private. Nothing is recorded while the
desktop's privacy settings turn file history off.
"""

import dataclasses
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib, GObject  # noqa: E402

#: Files remembered; the least recently opened are forgotten first.
MAX_FILES = 100
#: Changes are written this long after the last one, and when the app quits.
SAVE_DELAY_MS = 1000
_FORMAT = 1
_FIT_MODES = ("width", "page", None)


@dataclasses.dataclass
class Entry:
    path: str
    #: When the file was last opened, in seconds since 1970.
    opened: float = 0.0
    #: Where the reader was: the page (from 0), the zoom, and the fit mode
    #: ("width", "page", or None for a fixed zoom).
    page: int = 0
    zoom: float = 1.0
    fit: str | None = "width"


def default_path() -> Path:
    state = os.environ.get("XDG_STATE_HOME", "")
    # The XDG rules say to ignore a relative path here.
    base = Path(state) if Path(state).is_absolute() else Path.home() / ".local" / "state"
    return base / "bluepencil" / "history.json"


def desktop_allows_history() -> Callable[[], bool]:
    """A check of the desktop's "File History" privacy setting.

    Without GNOME's settings, as on some other desktops, history is kept.
    """
    source = Gio.SettingsSchemaSource.get_default()
    schema = source.lookup("org.gnome.desktop.privacy", True) if source is not None else None
    if schema is None or not schema.has_key("remember-recent-files"):
        return lambda: True
    settings = Gio.Settings.new("org.gnome.desktop.privacy")
    return lambda: settings.get_boolean("remember-recent-files")


class History(GObject.Object):
    """Recent files, newest first. One instance serves every window."""

    __gtype_name__ = "BluepencilHistory"
    __gsignals__ = {
        # The list of recent files changed; a new position alone does not count.
        "changed": (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    def __init__(self, path: Path | None = None, allowed: Callable[[], bool] | None = None) -> None:
        super().__init__()
        self.path = path or default_path()
        self._allowed = allowed or desktop_allows_history()
        self._entries = _load(self.path)
        self._save_timer = 0

    def recent(self) -> list[Entry]:
        """Copies of the entries, most recently opened first."""
        return [dataclasses.replace(entry) for entry in self._entries]

    def lookup(self, path: str) -> Entry | None:
        entry = self._find(path)
        return dataclasses.replace(entry) if entry is not None else None

    def opened(self, path: str) -> None:
        """Put `path` at the top of the recent files."""
        if not self._allowed():
            return
        entry = self._find(path)
        if entry is None:
            entry = Entry(path)
        else:
            self._entries.remove(entry)
        entry.opened = time.time()
        self._entries.insert(0, entry)
        del self._entries[MAX_FILES:]
        self._schedule_save()
        self.emit("changed")

    def remember_position(self, path: str, page: int, zoom: float, fit: str | None) -> None:
        """Note where the reader is in `path`, if it is in the list."""
        entry = self._find(path)
        if entry is None or not self._allowed() or (entry.page, entry.zoom, entry.fit) == (page, zoom, fit):
            return
        entry.page, entry.zoom, entry.fit = page, zoom, fit
        self._schedule_save()

    def forget(self, path: str) -> None:
        entry = self._find(path)
        if entry is not None:
            self._entries.remove(entry)
            self._schedule_save()
            self.emit("changed")

    def clear(self) -> None:
        if self._entries:
            self._entries.clear()
            self._schedule_save()
            self.emit("changed")

    def save(self) -> None:
        """Write changes that are waiting, now."""
        if self._save_timer:
            GLib.source_remove(self._save_timer)
            self._save_timer = 0
            self._write()

    def _find(self, path: str) -> Entry | None:
        return next((entry for entry in self._entries if entry.path == path), None)

    def _schedule_save(self) -> None:
        if not self._save_timer:
            self._save_timer = GLib.timeout_add(SAVE_DELAY_MS, self._on_save_timer)

    def _on_save_timer(self) -> bool:
        self._save_timer = 0
        self._write()
        return GLib.SOURCE_REMOVE

    def _write(self) -> None:
        data = {"format": _FORMAT, "files": [dataclasses.asdict(entry) for entry in self._entries]}
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(data, stream, indent=1)
            # Replacing in one step means a crash never leaves half a file.
            temporary.replace(self.path)
        except OSError as error:
            print(f"Bluepencil: could not save the list of recent files: {error}", file=sys.stderr)


def _load(path: Path) -> list[Entry]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as error:
        print(f"Bluepencil: ignoring an unreadable list of recent files: {error}", file=sys.stderr)
        return []
    if not isinstance(data, dict) or data.get("format") != _FORMAT or not isinstance(data.get("files"), list):
        return []
    entries: list[Entry] = []
    for item in data["files"]:
        entry = _entry_from_json(item)
        if entry is not None and all(other.path != entry.path for other in entries):
            entries.append(entry)
    return entries[:MAX_FILES]


def _entry_from_json(item: object) -> Entry | None:
    """An entry from the file, or None if anything in it is wrong."""
    if not isinstance(item, dict):
        return None
    path, page, fit = item.get("path"), item.get("page"), item.get("fit")
    opened, zoom = _number(item.get("opened")), _number(item.get("zoom"))
    if (
        isinstance(path, str)
        and path.startswith("/")
        and opened is not None
        and isinstance(page, int)
        and not isinstance(page, bool)
        and page >= 0
        and zoom is not None
        and zoom > 0
        and fit in _FIT_MODES
    ):
        return Entry(path, opened, page, zoom, fit)
    return None


def _number(value: object) -> float | None:
    """`value` as a float if it is a number. JSON true and false do not count,
    although Python treats them as numbers."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)

# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unsaved changes left behind when Bluepencil stopped unexpectedly.

Each engine keeps its snapshots in a folder of its own, with a manifest that
says which file they belong to (core/session.py), and deletes the folder when
the interface tells it to quit. A folder whose processes are gone and whose
changes were never saved is what can be recovered.
"""

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from .core.places import MANIFEST, snapshots_root


@dataclass
class Recoverable:
    folder: Path
    #: The file the changes belong to (for a new document, where it would go).
    path: str
    untitled: bool
    #: The history as the engine's "open" request takes it.
    history: dict

    @property
    def name(self) -> str:
        return Path(self.path).name


def find_recoverable(root: Path | None = None) -> list[Recoverable]:
    """Changes that can be recovered. Folders left with nothing unsaved in
    them are deleted on the way."""
    root = root or snapshots_root()
    found = []
    for folder in sorted(root.glob("edits-*")) if root.is_dir() else []:
        manifest = _read_manifest(folder)
        if manifest is None or _running(manifest["engine"]) or _running(manifest["interface"]):
            continue  # unreadable, or still in use
        if manifest["position"] == manifest["saved_position"]:
            shutil.rmtree(folder, ignore_errors=True)
            continue
        history = {
            "folder": str(folder),
            "files": [str(folder / name) for name in manifest["files"]],
            "position": manifest["position"],
            "saved_position": manifest["saved_position"],
            "untitled": manifest["untitled"],
        }
        found.append(Recoverable(folder, manifest["path"], manifest["untitled"], history))
    return found


def discard(item: Recoverable) -> None:
    shutil.rmtree(item.folder, ignore_errors=True)


def _read_manifest(folder: Path) -> dict | None:
    try:
        manifest = json.loads((folder / MANIFEST).read_text())
    except (OSError, ValueError):
        return None
    valid = (
        isinstance(manifest, dict)
        and manifest.get("format") == 1
        and isinstance(manifest.get("path"), str)
        and isinstance(manifest.get("files"), list)
        and all(isinstance(name, str) and "/" not in name for name in manifest["files"])
        and isinstance(manifest.get("position"), int)
        and isinstance(manifest.get("saved_position"), int)
        and isinstance(manifest.get("engine"), int)
        and isinstance(manifest.get("interface"), int)
    )
    if not valid:
        return None
    manifest["untitled"] = bool(manifest.get("untitled"))
    return manifest


def _running(pid: int) -> bool:
    """True if a Bluepencil process with this number is running."""
    if pid <= 0:
        return False
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    return b"bluepencil" in command

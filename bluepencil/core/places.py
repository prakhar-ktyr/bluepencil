# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where the engine keeps its files (plan, D7). Plain Python: the interface
reads these places too, so this must never load the PDF library."""

import os
from pathlib import Path

#: In each snapshot folder: which file the snapshots belong to, and the
#: history, for recovery after a crash.
MANIFEST = "session.json"


def snapshots_root() -> Path:
    """Where snapshot folders live: ~/.cache/bluepencil/snapshots."""
    cache = os.environ.get("XDG_CACHE_HOME", "")
    base = Path(cache) if Path(cache).is_absolute() else Path.home() / ".cache"
    return base / "bluepencil" / "snapshots"


def jobs_root() -> Path:
    """Where heavy jobs leave their results until the user saves them."""
    return snapshots_root().parent / "jobs"

# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Leave unsaved changes behind, the way a crash of the whole app does."""

import subprocess
import sys

from bluepencil.core import protocol


def crash_after_rotating(path) -> dict:
    """Open `path` in an engine, rotate its first page, then let the
    interface "crash": the engine's input closes without a quit request.
    Returns the history the engine reported."""
    with subprocess.Popen(
        [sys.executable, "-m", "bluepencil.core.engine"], stdin=subprocess.PIPE, stdout=subprocess.PIPE
    ) as engine:
        assert engine.stdin is not None and engine.stdout is not None
        reply: dict = {}
        for request in (
            {"op": "open", "path": str(path), "id": 1},
            {"op": "edit", "action": "rotate", "pages": [0], "degrees": 90, "id": 2},
        ):
            protocol.write_message(engine.stdin, request)
            message = protocol.read_message(engine.stdout)
            assert message is not None
            reply = message[0]
            assert reply["ok"], reply
        engine.stdin.close()
        assert engine.wait(timeout=10) == 0
    return reply["history"]

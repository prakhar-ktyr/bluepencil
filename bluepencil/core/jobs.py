# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Heavy jobs, each in a process of its own (plan, D2): a file in, a file out.

The interface starts `python -m bluepencil.core.jobs`, writes one request as
a line of JSON to its standard input, and reads lines of JSON from its
standard output: {"stage": ..., "progress": ...} while the job runs, then
{"ok": true, ...} or {"ok": false, "error": ...}. It cancels a job by ending
the process. The result is written next to its target as a .part file and
renamed only when complete, so a cancelled job leaves no half-written file.
"""

import contextlib
import json
import os
import signal
import sys
from pathlib import Path
from typing import IO

import pymupdf

from .compress import CompressError, compress
from .document import OpenError
from .memory import release_memory_promptly


def run(request: dict, replies: IO[str]) -> dict:
    """Do the job `request` describes; returns the final reply."""

    def report(stage: str, fraction: float) -> None:
        replies.write(json.dumps({"stage": stage, "progress": round(fraction, 3)}) + "\n")
        replies.flush()

    if request.get("job") != "compress":
        return {"ok": False, "error": "unknown-job", "detail": str(request.get("job"))}
    target = Path(request["target"])
    partial = target.with_name(f".{target.name}.part")
    try:
        size = compress(request["source"], str(partial), request["preset"], request.get("password"), report)
        partial.replace(target)
    except (OpenError, CompressError) as error:
        return {"ok": False, "error": error.code, "detail": str(error)}
    except Exception as error:  # noqa: BLE001 - the job's one reply must say what went wrong
        return {"ok": False, "error": "failed", "detail": f"{type(error).__name__}: {error}"}
    finally:
        partial.unlink(missing_ok=True)
    return {"ok": True, "size": size}


def main() -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # the interface decides when a job stops
    release_memory_promptly()
    # Only replies may reach standard output; anything else goes to errors.
    replies = os.fdopen(os.dup(sys.stdout.fileno()), "w")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    pymupdf.TOOLS.mupdf_display_errors(False)
    try:
        request = json.loads(sys.stdin.readline())
    except ValueError:
        request = {}
    result = run(request if isinstance(request, dict) else {}, replies)
    with contextlib.suppress(BrokenPipeError):
        replies.write(json.dumps(result) + "\n")
        replies.close()


if __name__ == "__main__":
    main()

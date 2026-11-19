# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Runs one heavy job in a process of its own and reports on the main loop
(plan, D2). The job itself is in core/jobs.py."""

import contextlib
import json
import subprocess
import threading
from pathlib import Path

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib, GObject  # noqa: E402

from .engine_client import start_child  # noqa: E402


class Job(GObject.Object):
    """One job. Emits progress(stage, fraction), then finished(result)
    unless it is cancelled."""

    __gtype_name__ = "BluepencilJob"
    __gsignals__ = {
        "progress": (GObject.SignalFlags.RUN_LAST, None, (str, float)),
        # The job's final reply: {"ok": True, ...} or {"ok": False, "error": ...}.
        "finished": (GObject.SignalFlags.RUN_LAST, None, (object,)),
    }

    def __init__(self, request: dict) -> None:
        super().__init__()
        self.request = request
        self._process: subprocess.Popen | None = None
        self._result: dict | None = None
        self.cancelled = False

    @property
    def running(self) -> bool:
        return self._process is not None

    def start(self) -> None:
        process = start_child("bluepencil.core.jobs", text=True)
        self._process = process
        assert process.stdin is not None
        with contextlib.suppress(OSError):
            # The request, password included, goes through the pipe: other
            # programs can read a process's command line, not its input.
            process.stdin.write(json.dumps(self.request) + "\n")
            process.stdin.close()
        threading.Thread(target=self._read, args=(process,), name="bluepencil-job", daemon=True).start()

    def cancel(self) -> None:
        """Stop the job; no finished signal follows. A half-written result is removed."""
        self.cancelled = True
        process, self._process = self._process, None
        if process is not None:
            process.kill()
            process.wait()
        target = self.request.get("target")
        if target:
            Path(target).with_name(f".{Path(target).name}.part").unlink(missing_ok=True)

    def _read(self, process: subprocess.Popen) -> None:
        """Runs in a helper thread."""
        assert process.stdout is not None
        try:
            for line in process.stdout:
                with contextlib.suppress(ValueError):
                    GLib.idle_add(self._on_message, process, json.loads(line))
        except (OSError, ValueError):
            pass  # cancelled while reading
        finally:
            process.stdout.close()
        GLib.idle_add(self._on_ended, process)

    def _on_message(self, process: subprocess.Popen, message: object) -> bool:
        if process is self._process and isinstance(message, dict):
            if "ok" in message:
                self._result = message
            elif "stage" in message:
                self.emit("progress", str(message["stage"]), float(message.get("progress", 0)))
        return GLib.SOURCE_REMOVE

    def _on_ended(self, process: subprocess.Popen) -> bool:
        if process is self._process:
            self._process = None
            process.wait()
            self.emit("finished", self._result or {"ok": False, "error": "failed", "detail": "the job stopped"})
        return GLib.SOURCE_REMOVE

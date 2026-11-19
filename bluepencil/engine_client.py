# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Runs an engine process and talks to it from the interface.

The interface never calls the PDF library itself (plan, D1). It queues
requests here, and replies come back on the GTK main loop. Each request has a
priority and an optional key: a newer request with the same key replaces an
older one that has not been sent yet, so scrolling quickly does not pile up
renders of pages that have already left the screen.
"""

import contextlib
import heapq
import itertools
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Hashable
from pathlib import Path
from typing import IO

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib, GObject  # noqa: E402

from .core import protocol  # noqa: E402

ReplyHandler = Callable[[dict, bytes], None]

#: Requests handed to the engine before waiting for replies. Two keep it busy
#: while a reply travels back, without committing to work that a newer
#: request could make pointless.
MAX_IN_FLIGHT = 2

_PACKAGE_ROOT = str(Path(__file__).resolve().parent.parent)


def start_child(module: str, *, text: bool = False) -> subprocess.Popen:
    """Start `python -m module` from this copy of Bluepencil, with pipes for
    its standard input and output."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [_PACKAGE_ROOT, env.get("PYTHONPATH")]))
    return subprocess.Popen(
        [sys.executable, "-m", module], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, text=text
    )


class EngineClient(GObject.Object):
    """One engine process. It can be started again after a crash."""

    __gtype_name__ = "BluepencilEngineClient"
    __gsignals__ = {
        # The process ended without being asked to. Requests not yet
        # answered are forgotten.
        "died": (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    def __init__(self) -> None:
        super().__init__()
        self._process: subprocess.Popen[bytes] | None = None
        self._queue: list[tuple[int, int, Hashable]] = []
        self._waiting: dict[Hashable, tuple[int, dict, ReplyHandler]] = {}
        self._sent: dict[int, ReplyHandler] = {}
        self._order = itertools.count()
        self._ids = itertools.count(1)

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    @property
    def running(self) -> bool:
        return self._process is not None

    def start(self) -> None:
        """Start the engine process, unless it is already running."""
        if self._process is not None:
            return
        process = start_child("bluepencil.core.engine")
        self._process = process
        threading.Thread(
            target=self._read_replies,
            args=(process,),
            name="bluepencil-engine-replies",
            daemon=True,
        ).start()

    def request(
        self,
        request: dict,
        on_reply: ReplyHandler,
        *,
        priority: int = 0,
        key: Hashable | None = None,
    ) -> None:
        """Queue `request`; `on_reply(reply, payload)` runs on the main loop.

        Lower `priority` numbers go first. A queued request with the same
        `key` is replaced.
        """
        order = next(self._order)
        if key is None:
            key = ("unkeyed", order)
        self._waiting[key] = (order, request, on_reply)
        heapq.heappush(self._queue, (priority, order, key))
        self._send_waiting()

    def cancel(self, key: Hashable) -> None:
        """Forget a request that has not been sent to the engine yet."""
        self._waiting.pop(key, None)

    def close(self, keep_snapshots: bool = False) -> None:
        """Stop the engine process and forget every request.

        With `keep_snapshots`, the engine is not asked to quit, only left: it
        then keeps its snapshots, so unsaved changes can be recovered later.
        """
        process, self._process = self._process, None
        self._forget_requests()
        if process is None:
            return
        with contextlib.suppress(OSError, ValueError):
            if not keep_snapshots:
                protocol.write_message(_stdin(process), {"op": "quit", "id": 0})
            _stdin(process).close()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def _forget_requests(self) -> None:
        self._queue.clear()
        self._waiting.clear()
        self._sent.clear()

    def _send_waiting(self) -> None:
        process = self._process
        while process is not None and self._queue and len(self._sent) < MAX_IN_FLIGHT:
            _priority, order, key = heapq.heappop(self._queue)
            entry = self._waiting.get(key)
            if entry is None or entry[0] != order:
                continue  # cancelled, or replaced by a newer request
            del self._waiting[key]
            _order, request, on_reply = entry
            request_id = next(self._ids)
            self._sent[request_id] = on_reply
            try:
                protocol.write_message(_stdin(process), {**request, "id": request_id})
            except (OSError, ValueError):
                return  # the process is gone; _on_process_ended reports it

    def _read_replies(self, process: subprocess.Popen[bytes]) -> None:
        """Runs in a helper thread and passes each reply to the main loop."""
        replies = process.stdout
        assert replies is not None  # started with stdout=PIPE
        try:
            while (message := protocol.read_message(replies)) is not None:
                GLib.idle_add(self._on_reply, process, *message)
        except (OSError, ValueError, protocol.ProtocolError):
            pass
        finally:
            replies.close()
        GLib.idle_add(self._on_process_ended, process)

    def _on_reply(self, process: subprocess.Popen[bytes], reply: dict, payload: bytes) -> bool:
        if process is self._process:
            request_id = reply.get("id")
            on_reply = self._sent.pop(request_id, None) if isinstance(request_id, int) else None
            try:
                if on_reply is not None:
                    on_reply(reply, payload)
            finally:
                self._send_waiting()
        return GLib.SOURCE_REMOVE

    def _on_process_ended(self, process: subprocess.Popen[bytes]) -> bool:
        if process is self._process:  # not asked to stop: it crashed
            self._process = None
            self._forget_requests()
            with contextlib.suppress(OSError):  # the unsent data has nowhere to go
                _stdin(process).close()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            self.emit("died")
        return GLib.SOURCE_REMOVE


def _stdin(process: subprocess.Popen[bytes]) -> IO[bytes]:
    assert process.stdin is not None  # started with stdin=PIPE
    return process.stdin

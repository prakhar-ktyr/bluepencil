# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The interface's side of the engine: queueing, replacing, crashes."""

import os
import signal
import time

import gi
import pytest

gi.require_version("GLib", "2.0")
from gi.repository import GLib  # noqa: E402

from bluepencil.engine_client import EngineClient  # noqa: E402


def wait_for(condition, timeout=10.0):
    """Run the main loop until condition() is true."""
    loop = GLib.MainLoop()
    deadline = time.monotonic() + timeout

    def check():
        if condition() or time.monotonic() > deadline:
            loop.quit()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    GLib.timeout_add(10, check)
    loop.run()
    assert condition(), "timed out"


@pytest.fixture
def client():
    engine = EngineClient()
    engine.start()
    yield engine
    engine.close()


def test_opens_and_renders(client, make_pdf):
    replies = []
    client.request({"op": "open", "path": str(make_pdf())}, lambda reply, _: replies.append(reply))
    client.request(
        {"op": "render", "page": 1, "scale": 0.5},
        lambda reply, pixels: replies.append((reply, len(pixels))),
    )
    wait_for(lambda: len(replies) == 2)
    assert replies[0]["ok"] and replies[0]["page_count"] == 3
    reply, size = replies[1]
    assert reply["ok"] and size == reply["stride"] * reply["height"]


def test_newer_request_with_the_same_key_replaces_a_queued_one(client):
    calls = []
    # The first two requests go straight to the engine; the rest wait their turn.
    client.request({"op": "ping"}, lambda *_: calls.append("first"))
    client.request({"op": "ping"}, lambda *_: calls.append("second"))
    client.request({"op": "ping"}, lambda *_: calls.append("old"), key="page")
    client.request({"op": "ping"}, lambda *_: calls.append("new"), key="page")
    wait_for(lambda: "new" in calls)
    assert calls == ["first", "second", "new"]


def test_higher_priority_goes_first_and_cancelled_never_runs(client):
    calls = []
    client.request({"op": "ping"}, lambda *_: calls.append("busy 1"))
    client.request({"op": "ping"}, lambda *_: calls.append("busy 2"))
    client.request({"op": "ping"}, lambda *_: calls.append("later"), priority=1)
    client.request({"op": "ping"}, lambda *_: calls.append("sooner"), priority=0)
    client.request({"op": "ping"}, lambda *_: calls.append("cancelled"), key="gone")
    client.cancel("gone")
    wait_for(lambda: "later" in calls)
    wait_for(lambda: True, timeout=0.2)
    assert calls == ["busy 1", "busy 2", "sooner", "later"]


def test_reports_a_crash_and_starts_again(client):
    died = []
    client.connect("died", lambda _client: died.append(True))
    old_pid = client.pid
    os.kill(old_pid, signal.SIGKILL)
    wait_for(lambda: died)
    assert not client.running

    client.start()
    assert client.pid != old_pid
    replies = []
    client.request({"op": "ping"}, lambda reply, _: replies.append(reply))
    wait_for(lambda: replies)
    assert replies[0]["ok"]


def test_close_stops_the_process_quietly(make_pdf):
    engine = EngineClient()
    died = []
    engine.connect("died", lambda _engine: died.append(True))
    engine.start()
    pid = engine.pid
    assert pid is not None
    engine.close()
    wait_for(lambda: True, timeout=0.3)
    assert not died
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)

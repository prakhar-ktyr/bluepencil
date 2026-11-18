# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The engine as its own process, spoken to through the message protocol."""

import os
import subprocess
import sys

import pytest

from bluepencil.core import protocol


@pytest.fixture
def engine():
    with subprocess.Popen(
        [sys.executable, "-m", "bluepencil.core.engine"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    ) as process:
        yield process
        if process.poll() is None:
            process.kill()


def ask(process, request):
    protocol.write_message(process.stdin, request)
    return protocol.read_message(process.stdout)


def test_opens_and_renders(engine, make_pdf):
    reply, _ = ask(engine, {"op": "open", "path": str(make_pdf()), "id": 1})
    assert reply["ok"] and reply["id"] == 1 and reply["page_count"] == 3
    reply, pixels = ask(engine, {"op": "render", "page": 2, "scale": 1.0, "id": 2})
    assert reply["ok"] and reply["id"] == 2
    assert (reply["width"], reply["height"]) == (595, 842)
    assert len(pixels) == reply["stride"] * reply["height"]


def test_bad_requests_get_errors_and_the_engine_carries_on(engine, make_pdf, tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"garbage " * 200)
    # The PDF library complains loudly about this file; none of it may
    # leak into the replies.
    reply, _ = ask(engine, {"op": "open", "path": str(broken), "id": 1})
    assert not reply["ok"] and reply["error"] in ("damaged", "no-pages")
    reply, _ = ask(engine, {"op": "open", "path": str(make_pdf()), "id": 2})
    assert reply["ok"]
    reply, _ = ask(engine, {"op": "render", "page": 99, "scale": 1.0, "id": 3})
    assert reply == {"ok": False, "error": "internal", "detail": "IndexError: there is no page 99", "id": 3}
    reply, _ = ask(engine, {"op": "ping", "id": 4})
    assert reply == {"ok": True, "id": 4}


def test_quits_when_asked(engine):
    reply, _ = ask(engine, {"op": "quit", "id": 7})
    assert reply == {"id": 7, "ok": True}
    assert engine.wait(timeout=5) == 0


def test_quits_when_the_interface_goes_away(engine):
    engine.stdin.close()
    assert engine.wait(timeout=5) == 0


def start_engine():
    return subprocess.Popen(
        [sys.executable, "-m", "bluepencil.core.engine"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )


def test_edits_survive_the_engine_being_killed(make_pdf):
    path = str(make_pdf(pages=4))
    with start_engine() as first:
        assert ask(first, {"op": "open", "path": path, "id": 1})[0]["ok"]
        reply, _ = ask(first, {"op": "edit", "action": "rotate", "pages": [0], "degrees": 90, "id": 2})
        assert reply["ok"] and reply["select"] == [0] and reply["modified"]
        reply, _ = ask(first, {"op": "edit", "action": "delete", "pages": [3], "id": 3})
        assert reply["page_count"] == 3
        history = reply["history"]
        first.kill()

    with start_engine() as second:
        reply, _ = ask(second, {"op": "open", "path": path, "history": history, "id": 1})
        assert reply["ok"] and reply["page_count"] == 3
        assert reply["can_undo"] and reply["modified"]
        reply, _ = ask(second, {"op": "undo", "id": 2})
        assert reply["page_count"] == 4
        reply, _ = ask(second, {"op": "quit", "id": 3})
        assert second.wait(timeout=5) == 0
    # A clean exit deletes the snapshots.
    assert not any(os.path.exists(name) for name in history["files"])


def test_a_refused_edit_says_why(engine, make_pdf):
    ask(engine, {"op": "open", "path": str(make_pdf(pages=2)), "id": 1})
    reply, _ = ask(engine, {"op": "edit", "action": "delete", "pages": [0, 1], "id": 2})
    assert reply["ok"] is False and reply["error"] == "no-pages-left"
    reply, _ = ask(engine, {"op": "save", "path": "/nonexistent-folder/out.pdf", "id": 3})
    assert reply["ok"] is False and reply["error"] == "write-failed"

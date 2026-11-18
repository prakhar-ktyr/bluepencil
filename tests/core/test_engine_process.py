# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The engine as its own process, spoken to through the message protocol."""

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

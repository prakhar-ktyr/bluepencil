# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The engine process: holds one open document and answers requests.

The interface starts it as `python -m bluepencil.core.engine` (see
bluepencil/engine_client.py). Requests arrive on standard input and replies
leave on standard output, framed by protocol.py. Nothing else may reach
standard output, so anything the PDF library prints goes to standard error.
"""

import os
import signal
import sys
from typing import BinaryIO

import pymupdf

from . import protocol
from .document import OpenError, describe, open_document
from .render import render_page


class Engine:
    """Answers requests, one at a time, about one document."""

    def __init__(self) -> None:
        self.document: pymupdf.Document | None = None

    def handle(self, request: dict) -> tuple[dict, bytes]:
        op = request.get("op")
        if op == "open":
            return self._open(request["path"], request.get("password"))
        if op == "render":
            if self.document is None:
                return {"ok": False, "error": "no-document"}, b""
            info, pixels = render_page(
                self.document, request["page"], request["scale"], request.get("clip")
            )
            return {"ok": True, "page": request["page"], **info}, pixels
        if op == "ping":
            return {"ok": True}, b""
        return {"ok": False, "error": "unknown-request", "detail": str(op)}, b""

    def _open(self, path: str, password: str | None) -> tuple[dict, bytes]:
        if self.document is not None:
            self.document.close()
            self.document = None
        try:
            self.document = open_document(path, password)
        except OpenError as error:
            return {"ok": False, "error": error.code, "detail": error.detail}, b""
        return {"ok": True, **describe(self.document)}, b""


def serve(requests: BinaryIO, replies: BinaryIO) -> None:
    """Answer requests until asked to quit or the interface goes away."""
    engine = Engine()
    while (message := protocol.read_message(requests)) is not None:
        request, _payload = message
        if request.get("op") == "quit":
            protocol.write_message(replies, {"id": request.get("id"), "ok": True})
            return
        try:
            reply, data = engine.handle(request)
        except Exception as error:  # noqa: BLE001 - one bad request must not end the engine
            detail = f"{type(error).__name__}: {error}"
            reply, data = {"ok": False, "error": "internal", "detail": detail}, b""
        reply["id"] = request.get("id")
        protocol.write_message(replies, reply, data)


def main() -> None:
    # Ctrl+C in a terminal reaches every process of the app. The interface
    # decides when the engine stops, by closing its standard input.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    replies = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    pymupdf.TOOLS.mupdf_display_errors(False)
    if hasattr(pymupdf.TOOLS, "mupdf_display_warnings"):
        pymupdf.TOOLS.mupdf_display_warnings(False)
    try:
        serve(sys.stdin.buffer, replies)
    except (BrokenPipeError, protocol.ProtocolError):
        pass  # the interface went away
    finally:
        try:
            replies.close()
        except BrokenPipeError:
            pass


if __name__ == "__main__":
    main()

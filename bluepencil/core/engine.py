# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The engine process: holds one open document and answers requests.

The interface starts it as `python -m bluepencil.core.engine` (see
bluepencil/engine_client.py). Requests arrive on standard input and replies
leave on standard output, framed by protocol.py. Nothing else may reach
standard output, so anything the PDF library prints goes to standard error.
"""

import contextlib
import os
import signal
import sys
from collections.abc import Callable
from typing import IO

import pymupdf

from . import pages, protocol
from .document import OpenError
from .memory import release_memory_promptly
from .pages import PageError
from .render import render_page
from .session import SaveError, Session

#: Edits by name: each takes the document and the request, changes the
#: document, and returns the pages to select.
EDITS: dict[str, Callable[[pymupdf.Document, dict], list[int]]] = {
    "rotate": lambda document, request: pages.rotate(document, request["pages"], request["degrees"]),
    "delete": lambda document, request: pages.delete(document, request["pages"]),
    "duplicate": lambda document, request: pages.duplicate(document, request["pages"]),
    "move": lambda document, request: pages.move(document, request["pages"], request["to"]),
    "insert-blank": lambda document, request: pages.insert_blank(document, request["at"]),
    "insert-pdf": lambda document, request: pages.insert_pdf(
        document, request["path"], request["at"], request.get("password")
    ),
    "insert-image": lambda document, request: pages.insert_image(document, request["path"], request["at"]),
    "insert-files": lambda document, request: pages.insert_files(document, request["paths"], request["at"]),
}


def _failure(error: OpenError | PageError | SaveError) -> tuple[dict, bytes]:
    return {"ok": False, "error": error.code, "detail": str(error)}, b""


class Engine:
    """Answers requests, one at a time, about one document."""

    def __init__(self) -> None:
        self.session: Session | None = None
        #: Requests about the open document, by name.
        self._handlers: dict[str, Callable[[Session, dict], tuple[dict, bytes]]] = {
            "render": self._render,
            "edit": self._edit,
            "undo": self._undo,
            "redo": self._redo,
            "save": self._save,
            "extract": self._extract,
            "split": self._split,
        }

    def handle(self, request: dict) -> tuple[dict, bytes]:
        op = str(request.get("op"))
        starts = {"open": self._open, "combine": self._combine, "ping": lambda _request: ({"ok": True}, b"")}
        if op in starts:
            return starts[op](request)
        handler = self._handlers.get(op)
        if handler is None:
            return {"ok": False, "error": "unknown-request", "detail": str(op)}, b""
        if self.session is None:
            return {"ok": False, "error": "no-document"}, b""
        try:
            return handler(self.session, request)
        except (OpenError, PageError, SaveError) as error:
            return _failure(error)

    def _render(self, session: Session, request: dict) -> tuple[dict, bytes]:
        info, pixels = render_page(session.document, request["page"], request["scale"], request.get("clip"))
        return {"ok": True, "page": request["page"], **info}, pixels

    def _edit(self, session: Session, request: dict) -> tuple[dict, bytes]:
        change = EDITS.get(str(request.get("action")))
        if change is None:
            return {"ok": False, "error": "unknown-request", "detail": str(request.get("action"))}, b""
        selection = session.edit(lambda document: change(document, request))
        return {"ok": True, "select": selection, **session.state()}, b""

    def _undo(self, session: Session, _request: dict) -> tuple[dict, bytes]:
        session.undo()
        return {"ok": True, **session.state()}, b""

    def _redo(self, session: Session, _request: dict) -> tuple[dict, bytes]:
        session.redo()
        return {"ok": True, **session.state()}, b""

    def _save(self, session: Session, request: dict) -> tuple[dict, bytes]:
        session.save(request.get("path"))
        return {"ok": True, **session.state()}, b""

    def _extract(self, session: Session, request: dict) -> tuple[dict, bytes]:
        pages.extract(session.document, request["pages"], request["path"], session.password)
        return {"ok": True}, b""

    def _split(self, session: Session, request: dict) -> tuple[dict, bytes]:
        written = pages.split(session.document, request["groups"], request["folder"], request["stem"], session.password)
        return {"ok": True, "paths": written}, b""

    def close(self) -> None:
        if self.session is not None:
            self.session.close()
            self.session = None

    def _combine(self, request: dict) -> tuple[dict, bytes]:
        """Make a new document from several files."""
        self.close()
        try:
            self.session = Session.combine(request["paths"], request["path"])
        except (OpenError, PageError) as error:
            return _failure(error)
        return {"ok": True, **self.session.state()}, b""

    def _open(self, request: dict) -> tuple[dict, bytes]:
        """Open a file, or carry on from the snapshots of an engine that stopped."""
        self.close()
        path, password, history = request["path"], request.get("password"), request.get("history")
        try:
            if history:
                self.session = Session.resume(
                    path,
                    password,
                    folder=history["folder"],
                    files=history["files"],
                    position=history["position"],
                    saved_position=history["saved_position"],
                    untitled=history.get("untitled", False),
                )
            else:
                self.session = Session(path, password)
        except OpenError as error:
            return _failure(error)
        return {"ok": True, **self.session.state()}, b""


def serve(requests: IO[bytes], replies: IO[bytes]) -> None:
    """Answer requests until asked to quit or the interface goes away."""
    engine = Engine()
    try:
        _answer(engine, requests, replies)
    finally:
        # Snapshots are kept only if the process dies without getting here:
        # then they are what a new engine carries on from.
        engine.close()


def _answer(engine: Engine, requests: IO[bytes], replies: IO[bytes]) -> None:
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
    release_memory_promptly()
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
        with contextlib.suppress(BrokenPipeError):
            replies.close()


if __name__ == "__main__":
    main()

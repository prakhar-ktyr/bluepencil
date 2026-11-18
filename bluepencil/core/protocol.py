# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Messages between the interface and an engine process.

A message is a small JSON header plus an optional block of raw bytes, such as
the pixels of a page. On the wire: two big-endian 32-bit lengths, then the
header, then the bytes. Both sides use this module, so it must not import GTK
or the PDF library.
"""

import json
import struct
from typing import BinaryIO

_LENGTHS = struct.Struct("!II")
_MAX_HEADER = 1 << 20


class ProtocolError(Exception):
    """The other side sent something that is not a valid message."""


def write_message(stream: BinaryIO, header: dict, payload: bytes = b"") -> None:
    data = json.dumps(header, separators=(",", ":")).encode("utf-8")
    stream.write(_LENGTHS.pack(len(data), len(payload)))
    stream.write(data)
    if payload:
        stream.write(payload)
    stream.flush()


def read_message(stream: BinaryIO) -> tuple[dict, bytes] | None:
    """Read one message, or return None if the stream ended between messages."""
    lengths = _read_exactly(stream, _LENGTHS.size, end_ok=True)
    if lengths is None:
        return None
    header_size, payload_size = _LENGTHS.unpack(lengths)
    if not 0 < header_size <= _MAX_HEADER:
        raise ProtocolError(f"bad header size: {header_size}")
    try:
        header = json.loads(_read_exactly(stream, header_size))
    except ValueError as error:
        raise ProtocolError(f"bad header: {error}") from error
    payload = _read_exactly(stream, payload_size) if payload_size else b""
    return header, payload


def _read_exactly(stream: BinaryIO, size: int, end_ok: bool = False) -> bytes | None:
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            if end_ok and remaining == size:
                return None
            raise ProtocolError("the stream ended in the middle of a message")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)

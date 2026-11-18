# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Give memory back to the system promptly."""

import ctypes

#: mallopt() setting from glibc's malloc.h.
_M_MMAP_THRESHOLD = -3
#: Blocks at least this large come straight from the system and go straight
#: back when freed.
_THRESHOLD = 256 * 1024


def release_memory_promptly() -> None:
    """Return large blocks of memory to the system as soon as they are freed.

    Page images are megabytes each. By default glibc raises its threshold for
    such blocks after the first one is freed, then keeps freed blocks for
    reuse, so the interface's memory only ever grew: by about 200 MB for each
    file scrolled through, as measured with `./dev bench`. A fixed threshold
    keeps it at what is really in use. Without glibc this does nothing.
    """
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.mallopt(_M_MMAP_THRESHOLD, _THRESHOLD)
    except (OSError, AttributeError):
        pass

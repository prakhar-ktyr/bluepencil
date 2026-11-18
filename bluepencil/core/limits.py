# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Limits shared by the interface and the engine.

Deliberately free of imports, because both sides use it.
"""

#: Largest page image rendered in one piece, in pixels (about 48 MB of RGB).
MAX_PAGE_PIXELS = 16_000_000


def limit_scale(width_pt: float, height_pt: float, scale: float) -> float:
    """Reduce `scale` (pixels per point) so the image stays within MAX_PAGE_PIXELS."""
    pixels = width_pt * height_pt * scale * scale
    if pixels <= MAX_PAGE_PIXELS:
        return scale
    return scale * (MAX_PAGE_PIXELS / pixels) ** 0.5

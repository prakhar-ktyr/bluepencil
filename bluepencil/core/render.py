# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Turning pages into pixels. Runs in the engine process."""

import pymupdf

from .limits import limit_scale


def render_page(
    document: pymupdf.Document,
    index: int,
    scale: float,
    clip: list[float] | None = None,
) -> tuple[dict, bytes]:
    """Render page `index` (from 0) at `scale` pixels per point, as RGB.

    `clip` optionally limits the image to part of the page: [x0, y0, x1, y1]
    in points. Returns a description of the image and its bytes.
    """
    if not 0 <= index < document.page_count:
        raise IndexError(f"there is no page {index}")
    page = document[index]
    area = pymupdf.Rect(clip) if clip is not None else page.rect
    scale = limit_scale(area.width, area.height, scale)
    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(scale, scale),
        clip=area if clip is not None else None,
        alpha=False,
    )
    info = {
        "width": pixmap.width,
        "height": pixmap.height,
        "stride": pixmap.stride,
        "scale": scale,
    }
    return info, pixmap.samples

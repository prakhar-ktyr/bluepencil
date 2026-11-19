# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Make a PDF smaller: shrink its images, its fonts, and its structure.

Runs inside a job process (jobs.py), because it can take a while on a big
file. It never touches the file it reads: the result is a new file.
"""

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .document import KEEP_ENCRYPTION, open_document


@dataclass(frozen=True)
class Preset:
    #: Images sharper than `threshold` dots per inch are brought down to `dpi`.
    dpi: int
    threshold: int
    #: JPEG quality, from 0 to 100.
    quality: int
    #: Also turn lossless pictures (such as PNG) into JPEG. Smaller, but
    #: line art and screenshots can blur, so Print leaves them alone.
    lossless_pictures: bool


#: Presets by name. "lossless" changes no picture: it only removes what is
#: unused and packs the rest tighter.
PRESETS: dict[str, Preset | None] = {
    "email": Preset(dpi=96, threshold=120, quality=60, lossless_pictures=True),
    "balanced": Preset(dpi=150, threshold=200, quality=75, lossless_pictures=True),
    "print": Preset(dpi=300, threshold=400, quality=85, lossless_pictures=False),
    "lossless": None,
}

Progress = Callable[[str, float], None]


class CompressError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def compress(
    source: str,
    target: str,
    preset: str,
    password: str | None = None,
    progress: Progress = lambda _stage, _fraction: None,
) -> int:
    """Write a smaller copy of `source` to `target`; return its size in bytes.

    `progress(stage, fraction)` is called as the work goes on. The copy keeps
    the source's password, page count, text and links.
    """
    if preset not in PRESETS:
        raise CompressError("unknown-preset", preset)
    settings = PRESETS[preset]
    progress("reading", 0.02)
    document = open_document(source, password)
    try:
        page_count = document.page_count
        if settings is not None:
            progress("pictures", 0.1)
            document.rewrite_images(
                dpi_threshold=settings.threshold,
                dpi_target=settings.dpi,
                quality=settings.quality,
                lossy=True,
                lossless=settings.lossless_pictures,
                # Black-and-white scans are already small, and JPEG would
                # make them larger and blurred.
                bitonal=False,
            )
        progress("fonts", 0.6)
        # Fonts that cannot be subset are kept whole: never a reason to fail.
        with contextlib.suppress(Exception):
            document.subset_fonts()
        progress("writing", 0.75)
        document.save(
            target,
            garbage=4,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            use_objstms=1,
            encryption=KEEP_ENCRYPTION,
        )
    finally:
        document.close()
    progress("checking", 0.95)
    check = open_document(target, password)
    try:
        if check.page_count != page_count:
            raise CompressError("check-failed", f"{check.page_count} pages instead of {page_count}")
    finally:
        check.close()
    progress("done", 1.0)
    return Path(target).stat().st_size

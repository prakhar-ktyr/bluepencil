# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compression, called directly and as a job process."""

import json
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest

from bluepencil.core.compress import PRESETS, CompressError, compress
from bluepencil.core.document import KEEP_ENCRYPTION


def texts(path, password=None) -> list[str]:
    document = pymupdf.open(path)
    if password:
        document.authenticate(password)
    return [page.get_text().strip() for page in document.pages()]


def looks_the_same(first, second) -> bool:
    """Pages match when seen small: what a person would notice."""
    a, b = pymupdf.open(first), pymupdf.open(second)
    for one, two in zip(a.pages(), b.pages(), strict=True):
        x, y = one.get_pixmap(dpi=20).samples, two.get_pixmap(dpi=20).samples
        if sum(abs(p - q) for p, q in zip(x, y, strict=True)) / len(x) > 12:
            return False
    return True


# The sample is noise, the hardest kind of photo to compress; real photos shrink more.
@pytest.mark.parametrize(("preset", "at_most"), [("email", 0.25), ("balanced", 0.5)])
def test_presets_that_shrink_pictures_make_photos_much_smaller(photos, tmp_path, preset, at_most):
    target = tmp_path / f"{preset}.pdf"
    stages: list[str] = []
    size = compress(str(photos), str(target), preset, progress=lambda stage, _fraction: stages.append(stage))
    assert size == target.stat().st_size
    assert size < photos.stat().st_size * at_most
    assert texts(target) == ["Page 1", "Page 2"]
    assert looks_the_same(photos, target)
    assert stages == ["reading", "pictures", "fonts", "writing", "checking", "done"]


def test_print_and_lossless_leave_lossless_pictures_alone(photos, tmp_path):
    for preset in ("print", "lossless"):
        target = tmp_path / f"{preset}.pdf"
        size = compress(str(photos), str(target), preset)
        # Nothing much to gain here: the caller tells the user so.
        assert size > photos.stat().st_size * 0.9
        assert texts(target) == ["Page 1", "Page 2"]


def test_the_password_stays(photos, tmp_path):
    locked = tmp_path / "locked.pdf"
    document = pymupdf.open(photos)
    document.save(locked, encryption=pymupdf.mupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
    target = tmp_path / "small.pdf"
    compress(str(locked), str(target), "email", password="secret")
    assert pymupdf.open(target).needs_pass
    assert texts(target, "secret") == ["Page 1", "Page 2"]
    assert KEEP_ENCRYPTION == pymupdf.mupdf.PDF_ENCRYPT_KEEP


def test_unknown_presets_are_refused(photos, tmp_path):
    with pytest.raises(CompressError):
        compress(str(photos), str(tmp_path / "out.pdf"), "tiny")
    assert set(PRESETS) == {"email", "balanced", "print", "lossless"}


def run_job(request: dict) -> list[dict]:
    result = subprocess.run(
        [sys.executable, "-m", "bluepencil.core.jobs"],
        input=json.dumps(request) + "\n",
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return [json.loads(line) for line in result.stdout.splitlines()]


def test_the_job_process_reports_progress_then_the_result(photos, tmp_path):
    target = tmp_path / "small.pdf"
    lines = run_job({"job": "compress", "source": str(photos), "target": str(target), "preset": "email"})
    progress, result = lines[:-1], lines[-1]
    assert [line["stage"] for line in progress][-1] == "done"
    assert all(0 <= line["progress"] <= 1 for line in progress)
    assert result == {"ok": True, "size": target.stat().st_size}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["photos.pdf", "small.pdf"]  # no .part left


def test_the_job_process_reports_failures(tmp_path):
    missing, target = str(tmp_path / "missing.pdf"), str(tmp_path / "x.pdf")
    lines = run_job({"job": "compress", "source": missing, "target": target, "preset": "email"})
    assert lines[-1]["ok"] is False and lines[-1]["error"] == "not-found"
    assert not list(Path(tmp_path).iterdir())

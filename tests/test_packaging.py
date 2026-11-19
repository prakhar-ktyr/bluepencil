# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The files that describe Bluepencil to the desktop and to the app stores."""

import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from bluepencil import APP_ID, VERSION

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DESKTOP = DATA / f"{APP_ID}.desktop"
METAINFO = DATA / f"{APP_ID}.metainfo.xml"
ICON = DATA / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"
SYMBOLIC = DATA / "icons" / "hicolor" / "symbolic" / "apps" / f"{APP_ID}-symbolic.svg"
RECIPE = ROOT / "snap" / "snapcraft.yaml"


def test_the_desktop_file_registers_bluepencil_for_pdfs():
    lines = DESKTOP.read_text().splitlines()
    assert "MimeType=application/pdf;" in lines
    assert f"Icon={APP_ID}" in lines
    assert "Exec=bluepencil %U" in lines


@pytest.mark.skipif(shutil.which("desktop-file-validate") is None, reason="desktop-file-utils is not installed")
def test_the_desktop_file_is_valid():
    result = subprocess.run(["desktop-file-validate", str(DESKTOP)], capture_output=True, text=True, check=False)
    assert (result.returncode, result.stdout) == (0, "")


def test_the_store_description_names_the_app_its_launcher_and_licence():
    root = ET.parse(METAINFO).getroot()
    assert root.findtext("id") == APP_ID
    assert root.findtext("launchable") == f"{APP_ID}.desktop"
    assert root.findtext("project_license") == "AGPL-3.0-or-later"


def test_the_store_screenshots_are_in_the_repository():
    # The stores fetch them from GitHub, so a renamed file breaks the listing.
    address = "https://raw.githubusercontent.com/prakhar-ktyr/bluepencil/main/"
    images = [image.text or "" for image in ET.parse(METAINFO).getroot().iter("image")]
    assert len(images) >= 3
    for image in images:
        assert image.startswith(address)
        assert (ROOT / image.removeprefix(address)).is_file(), image


@pytest.mark.skipif(shutil.which("appstreamcli") is None, reason="appstream is not installed")
def test_the_store_description_is_valid():
    result = subprocess.run(
        ["appstreamcli", "validate", "--no-net", str(METAINFO)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(("icon", "size"), [(ICON, "128"), (SYMBOLIC, "16")])
def test_the_icons_are_square(icon, size):
    root = ET.parse(icon).getroot()
    assert root.get("width") == root.get("height") == size


def under(header: str) -> list[str]:
    """The lines indented under `header`, a line of the snap recipe, without
    comments."""
    lines = RECIPE.read_text().splitlines()
    depth = len(header) - len(header.lstrip())
    block = []
    for line in lines[lines.index(header) + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if len(line) - len(line.lstrip()) <= depth:
            break
        block.append(line.strip())
    return block


def test_the_snap_is_confined_and_has_no_network_access():
    lines = RECIPE.read_text().splitlines()
    assert "confinement: strict" in lines
    assert under("    plugs:") == ["- home", "- removable-media"]
    assert f"    common-id: {APP_ID}" in lines


def test_the_snap_has_the_version_of_the_app():
    found = re.search(r"^version: '([^']+)'$", RECIPE.read_text(), re.MULTILINE)
    assert found is not None
    assert found.group(1) == VERSION


def test_the_snap_may_register_the_app_on_the_session_bus():
    # GTK owns the app ID as a bus name; a confined app that may not, quits.
    assert {"interface: dbus", "bus: session", f"name: {APP_ID}"} <= set(under("slots:"))

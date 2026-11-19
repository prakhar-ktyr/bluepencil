# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The files that describe Bluepencil to the desktop and to the app stores."""

import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from bluepencil import APP_ID

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DESKTOP = DATA / f"{APP_ID}.desktop"
METAINFO = DATA / f"{APP_ID}.metainfo.xml"
ICON = DATA / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"
SYMBOLIC = DATA / "icons" / "hicolor" / "symbolic" / "apps" / f"{APP_ID}-symbolic.svg"


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


def test_the_snap_is_confined_and_has_no_network_access():
    recipe = (ROOT / "snap" / "snapcraft.yaml").read_text()
    assert "confinement: strict" in recipe
    plugs = recipe.split("    plugs:")[1].split("    environment:")[0]
    assert [line.strip() for line in plugs.strip().splitlines()] == ["- home", "- removable-media"]
    assert f"common-id: {APP_ID}" in recipe

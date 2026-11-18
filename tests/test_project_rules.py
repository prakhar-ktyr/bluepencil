# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rules from the plan (section 11) that a test can check."""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "bluepencil"


def _imports(path: Path) -> set[str]:
    """Top-level names of the modules `path` imports."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_every_source_file_starts_with_the_licence_lines():
    sources = [*PACKAGE.rglob("*.py"), *(ROOT / "tests").rglob("*.py"), ROOT / "dev"]
    missing = [
        str(path.relative_to(ROOT))
        for path in sources
        if "SPDX-License-Identifier: AGPL-3.0-or-later" not in "\n".join(path.read_text().splitlines()[:4])
    ]
    assert not missing


def test_core_never_imports_gtk():
    offenders = [str(path.relative_to(ROOT)) for path in (PACKAGE / "core").rglob("*.py") if "gi" in _imports(path)]
    assert not offenders


def test_the_interface_never_loads_the_pdf_library():
    # Checked in a fresh process, so that indirect imports count too.
    script = """
import importlib, pkgutil, sys
import bluepencil
for module in pkgutil.walk_packages(bluepencil.__path__, "bluepencil."):
    if not module.name.startswith("bluepencil.core"):
        importlib.import_module(module.name)
loaded = sorted(name for name in sys.modules if name.split(".")[0] in ("pymupdf", "fitz"))
print(" ".join(loaded))
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, check=True, timeout=60
    )
    assert result.stdout.strip() == ""

# Bluepencil

[![Tests](https://github.com/prakhar-ktyr/bluepencil/actions/workflows/tests.yml/badge.svg)](https://github.com/prakhar-ktyr/bluepencil/actions/workflows/tests.yml)

A PDF app for Ubuntu and other Linux desktops: view, edit, sign, organize and
convert PDFs in one window, with every file staying on your computer.

**Status: early development.** Bluepencil opens PDFs, including
password-protected ones, and shows their pages with zoom, page navigation and
a thumbnail sidebar.
Editing features come next.

## Run from source

Bluepencil is written in Python with GTK 4 and libadwaita. On Ubuntu 24.04 or
newer, install the toolkit once:

```
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-venv xvfb
```

Then, from this folder:

```
./dev setup            # one-time: creates .venv with the PDF engine and test tools (about 30 MB download)
./dev                  # start the app
./dev run file.pdf     # start it with a file
```

`./dev` runs `python -m bluepencil` with the project's own Python. It also
clears the GTK settings that a snap-installed VS Code passes to its terminals,
which otherwise crash GTK 4 apps at startup.

## Run the tests

```
./dev test     # all tests
./dev check    # lint (ruff) and type checks (mypy)
```

The tests run on a hidden display (`xvfb`), so no windows appear on screen.

## Plan

The full plan (features, design, milestones and decisions) is in
[docs/PLAN.md](docs/PLAN.md). In short:

- **0.1:** read PDFs, organize pages (merge, split, reorder, rotate), compress
- **1.0:** search, copy text, print, annotate, fill forms and sign
- **2.0:** redaction, OCR, watermarks, passwords, text fixes, batch recipes
- **Later:** compare, extract, convert, scan from photos, read aloud

## Licence

Bluepencil is free software: you can redistribute it and modify it under the
terms of the GNU Affero General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any
later version. It comes with no warranty. See [LICENSE](LICENSE) for the full
text.

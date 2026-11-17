# Bluepencil

A PDF app for Ubuntu and other Linux desktops: view, edit, sign, organize and
convert PDFs in one window, with every file staying on your computer.

**Status: early development.** The app opens a window and accepts a PDF, but
does not display pages yet. The page viewer is the next feature.

## Run from source

Bluepencil is written in Python with GTK 4 and libadwaita. On Ubuntu 22.04 or
newer, install the toolkit once:

```
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-venv xvfb
```

Then, from this folder:

```
./dev setup            # one-time: creates .venv with the test tools
./dev                  # start the app
./dev run file.pdf     # start it with a file
```

`./dev` runs `python -m bluepencil` with the project's own Python. It also
clears the GTK settings that a snap-installed VS Code passes to its terminals,
which otherwise crash GTK 4 apps at startup.

## Run the tests

```
./dev test
```

The tests run on a hidden display (`xvfb`), so no windows appear on screen.

## Planned features

- Viewer with page thumbnails and search
- Page organizing: merge, split, reorder, rotate, delete
- Annotations, form filling and signing
- Compression
- Later: redaction, OCR, text editing, comparing two PDFs, converting

# Bluepencil plan

*Last updated: 18 November 2026.*

This is the working plan for the project: what the app is, every feature it
will have, how it is built, and the order of work. Tick the checkboxes as work
lands, and change the plan when reality disagrees with it.

**Where things stand:** Milestones 1 (viewer), 2 (organize pages) and 3
(compress) are built, with 213 tests, and Milestone 4 (package) has its
icon, desktop file, store metadata and a first snap recipe. Bluepencil opens, shows and remembers PDFs; rotates,
deletes, duplicates, moves, inserts, extracts and splits pages, alone or many
at once in Organize mode; combines files from any folders, put in order
first and unlocked if locked; undoes and redoes every change;
saves safely; keeps unsaved changes through an engine crash or a crash of
the whole app; and compresses to a smaller copy with four presets. Left in these milestones: checks by hand on a real desktop
(scrolling, memory, dragging pages, files opened in other apps after saving).
**Next action:** try it by hand (`./dev`), then build the snap with the
steps in Milestone 4. Publishing needs the Snap Store name reserved first
(only the owner of the Ubuntu One account can do that).

## Contents

1. [At a glance](#1-at-a-glance)
2. [What Bluepencil is](#2-what-bluepencil-is)
3. [Features](#3-features)
4. [How it looks](#4-how-it-looks)
5. [How it is built](#5-how-it-is-built)
6. [Implementation plan](#6-implementation-plan)
7. [Quality and releases](#7-quality-and-releases)
8. [Publishing](#8-publishing)
9. [Risks](#9-risks)
10. [Decisions](#10-decisions)
11. [Development rules](#11-development-rules)

---

## 1. At a glance

Bluepencil is a free PDF app for Ubuntu. It does in one window what today takes
several apps and an upload website: read, mark up, fill and sign, rearrange,
shrink, redact and convert PDFs. Everything runs on the user's computer, and
the packaged app has no network permission at all. Bluepencil is open source,
under the GNU Affero General Public License, version 3 or later (AGPL).

| Release | What a user can do | Effort | Reached by\* |
|---|---|---|---|
| **0.1** | Read PDFs, organize pages (merge, split, reorder, rotate) and compress. Installable from the Ubuntu App Center. | 4–5.5 weekends | mid to late December 2026 |
| **1.0** | Plus search, copy text, print, annotate, fill forms and sign. | 5–6.5 more (9–12 in total) | mid-January to early February 2027 |
| **2.0** | Plus true redaction, OCR, watermarks and page numbers, passwords, text fixes and batch recipes. | 8.5–11 more (17.5–23 in total) | late March to late April 2027 |
| **Later** | Compare, extract tables, convert, scan from photos, read aloud, certificate signatures, Flathub, offline assistant. | 1–2 weekends each | after 2.0 |

\* If every weekend from 21 November 2026 goes into it. One weekend means about
8 hours of hands-on time: trying things, reviewing and deciding. These are
ranges, not promises, and real life will stretch them.

Each release is usable on its own. If the project stopped after 0.1, there
would still be a finished, published app.

---

## 2. What Bluepencil is

### The problem

On Ubuntu, everyday PDF work is spread across several tools: Document Viewer
for reading and notes, PDF Arranger for pages, LibreOffice Draw for edits, a
browser for signing, and upload websites for everything else. As of November
2026 the free tools each cover one part of the job. The complete desktop
editors are paid (Master PDF Editor, PDF Studio) or come inside a full office
suite (OnlyOffice). Many people end up uploading private documents to a website
because it is the quickest way to compress or merge a file.

### Who it is for

People who handle PDFs as part of ordinary work and study: forms, contracts,
scans, bank statements, coursework. It is not aimed at print professionals.

### What makes it different

1. **One window for everything.** Viewing, editing, organizing and converting
   in the same app, with the same shortcuts and the same undo.
2. **Nothing leaves the computer.** The packaged app is sandboxed without
   network access, so it cannot upload a file even by mistake. The code is
   public, so anyone can check this; it is not just a promise.
3. **True redaction.** Marked content is deleted from the file, not covered
   with a black box, and the result is verified before it is saved.
4. **Batch recipes.** Chain steps such as OCR, compress and watermark, run them
   over a folder, and save the chain to reuse.
5. **It belongs on Ubuntu.** Native look, dark mode, keyboard shortcuts, and
   installation from the App Center.

### Principles

- **Offline, always.** No accounts, no telemetry, no ads, no update checks. The
  store delivers updates.
- **The original is safe.** Nothing is written to a user's file without an
  explicit Save. Tools that destroy information (redaction, compression,
  flattening) save a copy by default.
- **Every change can be undone** until the document is closed.
- **Fast on ordinary laptops.** Pages appear immediately and scrolling never
  waits for background work.
- **Standard files.** Annotations, form values and signatures are stored the
  standard PDF way, so other apps can read them.
- **Usable by everyone.** Keyboard access, screen-reader labels, high contrast.

### What it will not be

- Not a word processor. Text editing is for fixes, not for rewriting or
  reflowing pages.
- Not a design or prepress tool (no colour separations, no preflight).
- No cloud storage, sync or collaboration.
- No password cracking. It removes a password only when the user knows it.
- No Windows, Mac or mobile versions.

---

## 3. Features

The number is the release in which the feature first ships. "Later" means after
2.0, in an order to be decided.

### Open and view

| Feature | Release |
|---|---|
| Open PDFs from the file picker, by drag and drop, with "Open With", from the command line and from a recent-files list | 0.1 |
| Continuous scrolling with sharp pages at any zoom (fit width, fit page, 25–800 %) | 0.1 |
| Thumbnail sidebar and page-number box | 0.1 |
| Password-protected files (asks for the password) | 0.1 |
| Remembers page and zoom for each file | 0.1 |
| Full screen, presentation mode, rotate view | 0.2 |
| Tabs for several documents | 1.0 |
| Opens many damaged files and can save a repaired copy | 1.0 |

### Find and navigate

| Feature | Release |
|---|---|
| Search with every match highlighted and a results list | 0.2 |
| Select and copy text | 0.2 |
| Outline (table of contents) sidebar and clickable links | 0.2 |
| Print | 0.2 |
| Document properties: title, author, dates, page size, fonts, security | 0.2 |

### Organize pages

| Feature | Release |
|---|---|
| Page grid with drag-and-drop reordering and multi-select | 0.1 |
| Rotate, delete and duplicate pages | 0.1 |
| Extract pages to a new PDF | 0.1 |
| Insert pages from another PDF, a blank page, or an image | 0.1 |
| Merge several PDFs into one | 0.1 |
| Split by page ranges or every N pages | 0.1 |
| Split by bookmarks or by file size | 1.0 |
| Crop pages and change page size | 1.3 |

### Annotate

| Feature | Release |
|---|---|
| Highlight, underline and strike through text | 0.3 |
| Sticky notes and text boxes | 0.3 |
| Freehand pen (with stylus pressure) and eraser | 0.3 |
| Shapes: rectangle, ellipse, line, arrow | 0.3 |
| Annotation list in the sidebar; move, resize, recolour, delete | 0.3 |
| Flatten annotations into the page when saving a copy | 0.3 |
| Stamps: Approved, Draft, or your own image | 1.3 |

### Fill and sign

| Feature | Release |
|---|---|
| Fill interactive forms: text fields, checkboxes, radio buttons, dropdowns | 0.4 |
| Fill flat forms (scans and non-interactive PDFs): type anywhere, ticks, crosses, dates | 0.4 |
| Signatures: draw, type or import an image; stored on this computer only | 0.4 |
| Flatten a filled form so it can no longer be changed | 0.4 |
| Certificate (digital) signatures: sign and verify | Later |

### Edit content

| Feature | Release |
|---|---|
| Watermarks, page numbers, headers and footers, Bates numbers | 1.3 |
| Add text, images and shapes to a page | 1.5 |
| Fix existing text: typos, numbers, dates | 1.5 |
| Move, resize, replace or delete images | 1.5 |
| Edit links, the outline and document properties | 1.5 |

### Protect

| Feature | Release |
|---|---|
| True redaction: mark, review, apply, verify | 1.1 |
| Find and redact: a phrase, or patterns such as email addresses and phone numbers | 1.1 |
| Remove hidden data: metadata, comments, attachments, scripts, hidden layers | 1.1 |
| Add or change a password; restrict printing and copying (AES-256) | 1.4 |
| Remove a password you know | 1.4 |

### Optimize and convert

| Feature | Release |
|---|---|
| Compress with presets and a real before/after size | 0.1 |
| OCR: make scanned PDFs searchable and copyable, offline | 1.2 |
| Batch recipes: chain tools, run on many files, save and reuse | 2.0 |
| PDF to images, images to PDF | Later |
| Extract text, images and tables (to CSV or Excel) | Later |
| Word, Excel and PowerPoint to PDF | Later (Decision 4) |

### Beyond editing

| Feature | Release |
|---|---|
| Compare two PDFs: changed text side by side plus a visual overlay | Later |
| Scan to PDF from phone photos: straighten, crop, clean, OCR | Later |
| Read aloud with an offline voice | Later |
| Command-line interface for scripts | Later |
| Offline assistant: summarize, answer questions with page references | Later (Decision 5) |
| Interface translations | from 1.0 |
| Flathub release for other Linux systems | after 1.0 |

---

## 4. How it looks

One window per document until 1.0, then tabs.

```
┌───────────────────────────────────────────────────────────────────────────┐
│ [Open] [Save]   View │ Annotate │ Fill & Sign │ Organize │ Redact   Tools▾ ☰│  header bar
├───────────────────────────────────────────────────────────────────────────┤
│ tools for the current mode, e.g.  Highlight · Note · Text · Pen · Shapes   │  tool strip
├────────────┬──────────────────────────────────────────────────────────────┤
│ Thumbnails │                                                              │
│ Outline    │                                                              │
│ Notes      │                         page view                            │
│ Search     │                                                              │
│            │                                                              │
├────────────┴──────────────────────────────────────────────────────────────┤
│  ◀  3 / 120  ▶                                   −  100 %  +    Fit width │  bottom bar
└───────────────────────────────────────────────────────────────────────────┘
```

- **Modes** change the tool strip and what clicking on a page does. *View* is
  the default. *Organize* replaces the page view with a grid of pages. Modes
  appear as their release ships: 0.1 has View and Organize only, and an *Edit*
  mode joins in 1.5.
- **Tools** holds one-shot jobs that produce a new file: Compress, OCR,
  Protect, Watermark and numbering, Convert, Compare, Batch.
- **Sidebar** (F9) switches between thumbnails, outline, annotations and search
  results.
- **Start page** (no document open): an Open button, recent files, and
  "Combine files".

---

## 5. How it is built

### 5.1 Stack

| Part | Choice | Why |
|---|---|---|
| Language | Python 3.12 or newer | Quick to write and test; the strongest PDF libraries |
| Interface | GTK 4 with libadwaita | The native toolkit of Ubuntu's desktop |
| PDF engine | PyMuPDF, exact version pinned | One library covers rendering, text, annotations, forms, redaction, compression and OCR |
| Process layout | Interface, PDF engine and heavy jobs in separate processes | Keeps the interface smooth and survives engine crashes (5.3, D1) |
| OCR | Tesseract, built into PyMuPDF, with language files shipped in the app | Works offline |
| Certificate signatures (later) | pyHanko | PyMuPDF cannot sign with certificates |
| Package | Snap, strict confinement, `core24` base with the GNOME extension | App Center listing and a sandbox |
| Tests | pytest on a hidden display | No windows pop up; runs the same on a laptop and in CI |
| Automation | GitHub Actions | Free for public repositories; builds and publishes the snap |
| Licence | AGPL-3.0-or-later | Required by the PDF engine; suits a free Linux app (Decision 1) |

### 5.2 Structure

```
  Interface process          application.py, window.py, ui/
  (GTK 4, libadwaita)        never loads the PDF library
        │
        │  requests: "render page 4 at 150 %", "rotate pages 2 to 5"
        │  replies:  pixels, sizes, text, rectangles
        ▼
  Engine process             core/
  (one per open document)    the only code that calls the PDF library
        │
        ├── the open document, in memory
        ├── history: one snapshot file per edit (undo, redo, crash recovery)
        └── save: full rewrite to a temporary file, then replace the original

  Job processes              core/jobs.py
  (one per heavy job)        file in, file out: compress, OCR, batch, compare, convert
```

```
bluepencil/
  application.py, window.py     app shell (exists)
  engine_client.py              starts an engine process, sends requests, delivers replies
  core/                         runs inside engine and job processes; no GTK in here
    engine.py                   message loop: receives requests, calls the modules below
    document.py                 open, save, snapshots, page information
    render.py                   pages and regions of pages to pixels
    pages.py                    reorder, rotate, delete, insert, merge, split
    compress.py
    jobs.py                     entry point for heavy file-to-file jobs
    later: annotations.py, forms.py, redact.py, ocr.py, stamps.py,
           protect.py, edit.py, compare.py, recipes.py
  ui/                           widgets; no PDF library in here
    document_view.py, page_widget.py, sidebar.py, organize_view.py,
    dialogs/, tools/
data/                           icon, desktop file, store metadata
snap/snapcraft.yaml
tests/core/, tests/ui/
docs/PLAN.md                    this file
```

Two rules hold the structure together: `core/` never imports GTK, and `ui/`
never imports the PDF library. The first makes every PDF feature a plain
function that can be tested without a window or a second process. The second
is what keeps the interface smooth.

### 5.3 Design decisions

**D1. The PDF engine runs in its own process.** Each open document gets an
engine process that holds the document and is the only code calling the PDF
library. The interface sends it requests and gets plain data back: pixels,
sizes, text, rectangles. Requests have priorities (visible pages, then
thumbnails, then background work), and replies that are out of date, because
the zoom changed in the meantime, are dropped. There are two reasons, both
measured (5.4). Python runs one thing at a time inside a process, so PDF work
in the app's own process froze the interface for up to 100 ms per scanned page;
with the engine in a separate process the longest pause was 3 ms. And if a
damaged file crashes the PDF library, only the engine process dies: the app
restarts it and reopens the document from the newest snapshot.

**D2. Heavy jobs get a process of their own.** Compress, OCR, batch, compare
and convert take a file and produce a file, and can run for seconds or minutes.
Each runs as a separate short-lived process that reports progress and is
cancelled by ending it. The engine stays free to render pages while a job
runs, and the same job code will serve batch recipes and the command line.

**D3. Pages are rendered lazily.** The page view lays out a placeholder for
every page from its dimensions and asks the engine only for the pages on
screen plus two on either side. Rendered pages are kept in a cache with a
memory cap (256 MB by default). During zooming the old image is stretched
immediately and replaced by a sharp one once the zoom settles. The scroll
position for a new zoom is set before GTK lays the pages out: set from inside
GTK's layout pass, it is ignored for drawing and the old spot stays on screen.
Thumbnails follow the same rules at a lower priority, and only for rows inside
the open sidebar's visible area: GTK prepares about 200 rows ahead, even while
the sidebar is closed. At very high
zoom only the visible part of a page is rendered, so no single image grows
beyond about 16 megapixels. Search hits, selections and annotation handles are
painted by the page widget on top of the page image.

**D4. Undo works by snapshots.** After each edit the engine writes the whole
document to a snapshot file in the app's cache folder. Undo loads the previous
snapshot; redo loads the next. The last 30 steps are kept, or 1 GB of
snapshots, whichever is reached first, and never fewer than 5. Rapid small
edits, such as pen strokes less than a second apart, form one step. The newest
snapshot doubles as the recovery copy after a crash. Snapshots are deleted
when the document closes. PyMuPDF's built-in undo journal was tested and
rejected (5.4). If snapshots prove too slow on very large files, small edits
such as annotations can record their own reverse step instead.
Built in `core/session.py`. Each snapshot folder also holds `session.json`,
naming the file and the history, so that a new engine, or the next start of
the app, can carry on from it; the folder is deleted only once the changes
are saved or discarded.

**D5. Saving always rewrites the whole file.** Save writes a complete new file
to a temporary location, reopens it to confirm it is valid, and only then
replaces the original. PDF also allows "incremental" saves that append changes
to the old file; Bluepencil never uses them, because the old content, including
anything redacted, would still be inside the file. Redaction, compression and
flattening offer "Save a copy" with a suggested new name instead of Save. If
the document carries a certificate signature, the user is warned that saving
changes will invalidate it.

**D6. Privacy by construction.** The snap is strictly confined. It asks for
access to the home folder and, if the user enables it, removable drives. It
does not ask for network access. Files elsewhere are reached through the
system file picker, which grants access to the chosen file only. Scripts
inside PDFs are never run. External links ask before being handed to the
browser. There is no telemetry and no update check.

**D7. Where data lives.** Settings: `~/.config/bluepencil/settings.json`.
Recent files and where the reader left each one:
`~/.local/state/bluepencil/history.json`, readable by its owner only.
Saved signatures, stamps and recipes: `~/.local/share/bluepencil/`. Snapshots,
recovery copies and thumbnails: `~/.cache/bluepencil/`. Inside the snap these
paths sit under `~/snap/bluepencil/`. Settings are a plain JSON file, which
needs no installation step when running from source.

**D8. Compatibility floor: GTK 4.14, libadwaita 1.5, Python 3.12.** That is
Ubuntu 24.04, the development machine since 17 November 2026 (Decision 6).
The store build brings its own, newer copies (GTK 4.18, libadwaita 1.7 and
Python 3.12 in the `core24` GNOME runtime, checked on 18 November 2026), so
code written for the floor runs in both places, and CI tests both. The floor
only matters when running from source: users of the store build get the
bundled libraries on any Ubuntu from 20.04 on.

Everything in GTK 4.14 and libadwaita 1.5 is available, including
`Adw.ToolbarView`, `Adw.OverlaySplitView`, `Adw.Breakpoint`, `Adw.Dialog`,
`Adw.AlertDialog`, `Adw.AboutDialog` and `Gtk.FileDialog`. Too new for the
floor (confirmed missing on the development machine):

| Do not use | Added in | Use instead |
|---|---|---|
| `Adw.Spinner`, `Adw.BottomSheet`, `Adw.MultiLayoutView`, `Adw.ButtonRow` | libadwaita 1.6 | `Gtk.Spinner`, `Adw.Dialog`, `Adw.Breakpoint`, `Adw.ActionRow` |
| `Adw.ToggleGroup`, `Adw.WrapBox`, `Adw.InlineViewSwitcher` | libadwaita 1.7 | linked `Gtk.ToggleButton`s, `Gtk.FlowBox`, `Adw.ViewSwitcher` |
| `Adw.ShortcutsDialog` | libadwaita 1.8 | `Gtk.ShortcutsWindow` |

When unsure, check the "Available since" line in the documentation, or run
the code on Ubuntu 24.04.

### 5.4 What has been tested already

Measured on 17 November 2026 on the development machine (Ubuntu 22.04, 8 cores)
with PyMuPDF 1.28.2. These are quick probes, not benchmarks, but each one
removed a guess from this plan.

| Question | Result |
|---|---|
| Does the engine install and run here? | Yes. A 26 MB download, 63 MB on disk. |
| Is rendering fast enough? | Text pages take 1–5 ms at 2× zoom. A form page with heavy graphics took 55 ms. A 300-dpi scanned page took about 100 ms the first time it was drawn. |
| Is text work fast enough? | A 95-page manual: all text extracted in 72 ms, searched in 68 ms. |
| Does PDF work in the app's own process freeze the interface? | Yes, for exactly as long as each call runs: up to 100 ms for a scanned page. Drawing a scan in strips to shorten the calls made it worse (496 ms in total instead of 100 ms). |
| Does a separate engine process fix that? | Yes. While 84 scanned pages were rendered in 3 seconds, the longest interface pause was 3 ms. The process starts in about 0.12 s, and a page of pixels (6 MB) becomes a GTK image in about 4 ms. Hence D1. |
| Can pages be drawn in GTK 4.6? | Yes, three ways: as plain pictures, in a custom widget with an overlay painted on top, and as a thumbnail grid with multi-select. |
| Does redaction really remove text? | Yes. After apply and save, the text cannot be extracted, and the rest of the page is intact. |
| Does compression work? | Yes. An image-heavy test file shrank by over 95 %. The test images were synthetic, so real files will shrink less. |
| Forms, flattening, passwords? | Filling a field, flattening it into the page and AES-256 passwords all work. |
| OCR? | The recognition code is built into the engine. It needs language files, which are not on this machine and must ship with the app. |
| Can the engine's built-in undo journal be used? | No. It failed when adding a page, merging, and editing the outline or properties, and it broke text reading on rotated pages. Hence D4. |
| What does snapshot undo cost? | 27 ms for a 25 MB scan, 158 ms for a 126 MB scan, 83 ms for a 1,000-page text file. An artificial worst case, 1,000 pages built from 40,000 separate text insertions, took 1.1 s. |
| How slow is the most thorough clean-up on save? | 1 s for 25 MB, but 27 s for 126 MB. Normal Save must use lighter settings; the thorough ones belong to Compress and to saving after redaction. |

---

## 6. Implementation plan

Order of work: ship something real early, then add one visible capability per
release. Anything risky gets a small experiment before its milestone starts.

### Milestone 0: Foundations (nearly done; 2–3 hours left)

- [x] Name chosen and checked against the Snap Store, Flathub, GitHub and the web
- [x] Project folder and git repository
- [x] First window: Open button, file picker, About, Quit
- [x] `./dev` helper to run and test; 4 smoke tests
- [x] Feasibility checks of the PDF engine (5.4)
- [x] Decision 1: open source, AGPL-3.0-or-later (18 November 2026)
- [x] Licence: `LICENSE` file, a two-line licence header in every source file,
      copyright and licence shown in the About window
- [x] Push to GitHub (github.com/prakhar-ktyr/bluepencil) and set the app ID
      to `io.github.prakhar_ktyr.Bluepencil` (18 November 2026)
- [ ] Before accepting any outside code: set up a contributor licence
      agreement (for example the free CLA Assistant app on GitHub)
- [ ] Reserve the name `bluepencil` on the Snap Store
- [x] Decision 6: compatibility floor raised to Ubuntu 24.04 (18 November 2026)
- [ ] CI: run the tests on every push, on Ubuntu 24.04 and 26.04. The
      workflow is written (`.github/workflows/tests.yml`: each version in its
      own container, `./dev check` then `./dev test`) and passes actionlint;
      tick this once its first run on GitHub is green
- [x] `./dev check` for lint and type checks (ruff and mypy, exact versions),
      plus tests that every source file has its licence lines and that
      `core/` and the interface keep to their sides (rule 2 in section 11)

### Milestone 1: Viewer (1.5–2.5 weekends)

Engine

- [x] `core/engine.py`: the engine process and its message loop
- [x] `engine_client.py`: start, stop and restart an engine; send prioritized
      requests; deliver replies to the interface; drop stale replies
- [x] Open a file, with an optional password; report page count and page sizes;
      clear errors for damaged and unsupported files
- [x] Render a page, or a region of a page, to pixels at a given zoom
- [x] If an engine process dies, restart it and reopen the document

Interface

- [x] Scrolling page view with placeholders, lazy rendering and the image cache
- [x] Zoom: fit width, fit page, 25–800 %, Ctrl+scroll, pinch, keyboard
      (pinch is written but not yet tried on a touchpad)
- [x] Page navigation: the "3 / 120" box, Page Up and Down, Home and End
- [x] Thumbnail sidebar (F9), click to jump; slides over the pages in narrow
      windows
- [x] Open by drag and drop and from the command line; a second file opens a
      second window (drag and drop not yet tried by hand)
- [x] Start page with recent files: newest first, remove one or clear the
      list; files that have gone leave the list; nothing is recorded while
      the desktop's "File History" privacy setting is off
- [x] Password prompt; loading and error states
- [x] Remember page and zoom per file (and the fit mode)
- [x] Mark all interface text for translation

Tests

- [x] Engine functions called directly: page sizes, render dimensions,
      password, damaged file
- [x] Engine process: a request and its reply; recovery after the process is
      killed
- [x] Interface: open a generated sample, scroll, the right pages get rendered
- [x] `./dev bench`: a script that measures the budgets in section 7
      (`--quick` for a rough check in half a minute)

Progress on 18 November 2026: 72 tests pass. `./dev bench` on the hidden
display, after the fixes it led to (below):

| Measurement | Result | Budget |
|---|---|---|
| Open a 500-page file to first page visible | 0.49 s median, 0.56 s worst of 5 (was 0.86 s) | under 1 s |
| Longest pause for Bluepencil's own work while scrolling text, scans, and text at 200 % | 6.5 ms, 5.7 ms, 15.7 ms | under 20 ms |
| Page images in memory, scrolling 100 pages at 200 % | 255 MB | 256 MB |
| Drawing one frame (no graphics card on the hidden display) | 20–30 ms median, up to 180 ms | none |

What the benchmark found and what was done:

- **Closed windows were never freed**, with every page they had rendered:
  over 1 GB after a few files. Signal handlers on a window's own children
  formed reference cycles that Python's garbage collector cannot see. They
  are now connected weakly (`ui/weak.py`, rule 12), and a test checks that a
  closed window, its pages and its thumbnails are freed.
- **Freed memory was not returned to the system**: glibc kept freed page
  images for reuse, so memory grew by about 200 MB per file. Large blocks now
  go straight back (`core/memory.py`).
- **Opening was slow** because the hidden thumbnail list prepared about 200
  rows, the engine started only once a file was chosen, and every page was
  laid out twice. Thumbnails are now built when first shown, the engine starts
  with the window, and pages are fitted to the window before the first layout.

Still open:

- [ ] On a real desktop, check scrolling smoothness and memory. On the hidden
      display the interface process uses about 1.3 GB, because software
      OpenGL keeps its own copy of every page image; with the Cairo renderer
      it stays near 340 MB.
- [ ] Faster first layout and zoom: the view creates a widget for every page,
      and laying out 500 of them takes about 240 ms when a file opens and again
      after each zoom change. A view that only creates widgets for the pages on
      screen would remove both costs.

**Done when:** a 500-page file shows its first page in under a second and
scrolls smoothly, a 300-dpi scan scrolls just as smoothly, memory stays under
the cap, and killing the engine process loses nothing.

### Milestone 2: Organize pages (1–1.5 weekends)

Engine

- [x] Page operations: rotate, delete, duplicate, move, extract, insert a blank
      page, insert pages from another PDF (with its bookmarks), insert an image
      as a page (photos are scaled down to A4) — `core/pages.py`
- [x] Split by page ranges and every N pages; page ranges typed as "1-3, 5, 8-"
- [x] History: snapshots, undo, redo, limits (D4) — `core/session.py`.
      Grouping of rapid edits waits for annotations, the first edits that come
      in quick succession.
- [x] Save and Save As (D5): written next to the original, flushed to disk,
      reopened and checked, then put in its place; passwords, file
      permissions and links kept. PyMuPDF drops a file's password on save
      unless told to keep it, so every write passes `KEEP_ENCRYPTION`.
- [x] If the engine dies, a new one carries on from its snapshots, edits and
      history included
- [x] Recovery after the whole app stops unexpectedly: snapshots are deleted
      only when changes are saved or discarded; otherwise the next start
      offers them back (`recovery.py`), unsaved, with their undo history

Interface

- [x] Organize mode (Ctrl+G): page grid, multi-select, drag-and-drop
      reordering; a double click goes back to reading at that page
      (dragging not yet tried by hand: the tests call the drop handler)
- [x] Toolbar buttons and keyboard shortcuts for every page operation, so that
      nothing depends on dragging: Alt and the arrow keys move pages, Delete
      deletes them, Ctrl+[ and Ctrl+] rotate them
- [x] Drop PDF or image files onto the grid to insert them at that position,
      as one step that undo takes back
- [x] "Combine files" on the start page: pick PDFs and pictures, put the files
      in order in the Combine list, then the pages in the grid; Save asks
      where the new document goes
- [x] The Combine list numbers the files in their order and shows each one's
      first page and page count. Files move by dragging any part of them
      (the pointer turns into a hand), or from each file's menu, which shows
      the keys: Alt with ↑, ↓, Home or End moves the focused file. As in
      GNOME Settings, nothing depends on dragging, and moves are announced
      to screen readers. Add Files… and dropping from the Files app bring in
      files from any folder; files that cannot be combined say why, and locked PDFs
      are unlocked there (the new PDF has no password). Dropping several
      files on the window opens it. Files are read in an engine process of
      the list's own, one at a time, so a file that crashes the PDF library
      is named and cannot take an open document with it
- [x] Split dialog: every N pages, or ranges typed as "1-3, 4-10, 11-",
      checked as they are typed; the parts go to a chosen folder
- [x] Unsaved-changes marker, and Save / Discard / Cancel on close (also on
      Quit); Save, Save As, Undo, Redo, and rotate or delete the current page
      from the menu and shortcuts; a failed save offers Save As

Tests

- [x] Every operation, then undo and redo back to an identical document
- [x] Save round trip; merged files keep their bookmarks and links
- [ ] Manual check: saved files open correctly in Document Viewer and Firefox

**Done when:** reorder, rotate, delete, merge and split all work with undo, and
no test or manual check can make the app lose or corrupt a file.

### Milestone 3: Compress (half a weekend; built 19 November 2026)

- [x] `core/compress.py` with four presets: Email (images to about 96 dpi),
      Balanced (150 dpi), Print (300 dpi) and Lossless (clean-up only). It
      downsamples and recompresses images, subsets fonts and removes unused
      objects. Black-and-white scans are left alone (JPEG would enlarge them),
      and Print keeps lossless pictures lossless.
- [x] Runs as a job process (D2) with progress and cancel (`core/jobs.py`,
      `job_client.py`); the password travels through the pipe, never on the
      command line
- [x] Dialog: choose a preset, see the real resulting size, "Save a copy as…";
      unsaved changes are included, and the open file can never be the target
- [x] If the result is not smaller, say so and keep the original
- [x] Tests: output is smaller on an image-heavy sample; page count and text
      are unchanged; pages look the same within a tolerance

### Milestone 4: Package and publish 0.1 (1 weekend, plus store review)

- [x] App icon (SVG, plus a symbolic one), desktop file that registers
      Bluepencil for PDF files, store metadata file (`data/`); checked by
      `desktop-file-validate` and `appstreamcli validate` in the tests
- [ ] `snap/snapcraft.yaml`: `core24`, GNOME extension, strict confinement,
      `home` and `removable-media`, no `network`. **Drafted, not built yet:**
      snapcraft is not installed here. PyGObject comes from `python3-gi` in
      the Ubuntu archive; that is the part most likely to need a fix after
      the first build.
- [ ] Install the built snap and run the manual checklist: open and save inside
      the home folder, open a file from outside it through the file picker,
      drag and drop, dark mode, HiDPI, Wayland and X11
- [ ] CI builds the snap for amd64 and arm64 on every push to `main` and
      publishes it to the `edge` channel
- [ ] Store listing: summary, description, 3–5 screenshots, links, licence,
      category
- [ ] Tag `v0.1.0`, promote to `stable`, write the changelog

To build and try the snap (about 30 minutes the first time, mostly
downloads):

```
sudo snap install snapcraft --classic
sudo snap install lxd && sudo lxd init --auto   # snapcraft builds inside LXD
sudo usermod -aG lxd "$USER"                    # then log out and back in
snapcraft pack                                  # in the Bluepencil folder
sudo snap install --dangerous ./bluepencil_0.1.0_amd64.snap
snap run bluepencil
```

Packaging comes this early on purpose. The sandbox is where surprises hide
(file access, drag and drop, starting the engine process, printing), and
finding them with three features is cheaper than finding them with thirty.

### Release 0.2: Reading essentials (1–1.5 weekends)

- [ ] Search bar (Ctrl+F): all matches highlighted, next and previous, match
      count, results list in the sidebar, case and whole-word options
- [ ] Select text with the mouse; copy
- [ ] Outline sidebar; internal links jump; external links ask before opening
      the browser
- [ ] Print through the system print dialog, sending the PDF itself and not
      pictures of pages; verify inside the snap
- [ ] Properties dialog
- [ ] Full screen, presentation mode, rotate view

### Release 0.3: Annotate (1.5–2 weekends)

- [ ] `core/annotations.py`: add, list, change and delete standard PDF
      annotations
- [ ] Annotate mode: highlight, underline, strike through (on selected text),
      note, text box, pen, eraser, rectangle, ellipse, line, arrow
- [ ] Colour, thickness and opacity, remembered per tool
- [ ] Select, move, resize, delete; all undoable
- [ ] Annotation list in the sidebar
- [ ] Stylus pressure for the pen where the hardware provides it
- [ ] "Flatten annotations" when saving a copy
- [ ] Tests: each annotation type survives a save and is read back correctly

### Release 0.4: Fill and sign (1.5–2 weekends)

- [ ] `core/forms.py`: read and write form fields; flatten
- [ ] Interactive fields shown as real controls over the page; Tab moves
      between them; fields are highlighted
- [ ] Fill and Sign tools for flat forms: text anywhere, tick, cross, dot,
      today's date
- [ ] Signature dialog: draw, type, or import a photo of a signature with its
      background removed; save signatures locally; place and resize
- [ ] A clear note that this is a visual signature, not a certificate signature
- [ ] Tests: field values survive a save; flattened output has no fields; the
      signature lands at the right place and size

### Release 1.0: Polish (1 weekend)

- [ ] Tabs for several documents
- [ ] Preferences, keyboard-shortcuts window, restore the last session
- [ ] Split by bookmarks and by file size; save a repaired copy of a damaged file
- [ ] Accessibility pass: everything reachable by keyboard, labelled for screen
      readers, readable in high contrast
- [ ] Translation setup: all strings extracted, template published
- [ ] Performance pass against the budgets; test on Ubuntu 24.04 and 26.04
- [ ] Help page and first-run hints
- [ ] Check the name against trademark databases
- [ ] Release 1.0 to `stable`

### Release 1.1: Redaction (1.5–2 weekends)

- [ ] `core/redact.py`: mark, apply (text, images and drawings under a mark are
      removed), verify
- [ ] Redact mode: mark by dragging a box or from selected text; marks stay
      editable until applied
- [ ] Find and redact: a phrase, a regular expression, or built-in patterns
      (email addresses, phone numbers, card-like numbers)
- [ ] Review panel listing every mark before applying
- [ ] Applying always saves a new file, which is then reopened and searched to
      prove the content is gone
- [ ] "Remove hidden data": metadata, comments, attachments, scripts, hidden
      layers, embedded thumbnails
- [ ] Tests: redacted text cannot be extracted and is absent from the file's
      bytes; pixels under a mark are replaced; nothing outside a mark changes

### Release 1.2: OCR (1–1.5 weekends)

- [ ] `core/ocr.py`, as a job process: find pages without text, recognize the
      text, add it as an invisible layer under the page image
- [ ] Ship language files in the snap (Decision 3); more can be added by
      placing a language file in a folder
- [ ] Offer OCR when a scan is opened or when a search finds no text at all
- [ ] Progress, cancel, per-page results
- [ ] Tests on generated scans: known text is found afterwards; the page looks
      the same

With OCR in place, find-and-redact from 1.1 also works on scans.

### Release 1.3: Stamps and page layout (1 weekend)

- [ ] Watermark (text or image), page numbers, headers and footers, Bates
      numbers: position, font, page range, live preview
- [ ] Ready-made and custom stamps
- [ ] Crop pages and change page size

### Release 1.4: Passwords (half a weekend)

- [ ] Add or change the open password; restrict printing, copying and editing;
      AES-256
- [ ] Remove a password after the user enters it
- [ ] Plain explanation of what restrictions do and do not protect

### Release 1.5: Edit content (3–4 weekends)

- [ ] Edit mode: add text boxes, images and shapes as page content
- [ ] Move, resize, replace and delete existing images
- [ ] Fix existing text: click a line and edit it in place. The document's own
      font is reused when it contains the needed characters; otherwise the
      closest available font is used and the user is told.
- [ ] Edit links, the outline and document properties
- [ ] Tests on real-world documents: simple fonts, partially embedded fonts,
      rotated pages

Scope guard: line-level fixes only. No reflowing of paragraphs across lines or
pages. This is the hardest feature in the plan, because most PDFs embed only
the characters they use, so a replacement character often has no matching font.

### Release 2.0: Batch recipes (1.5–2 weekends)

- [ ] `core/recipes.py`: a recipe is an ordered list of steps stored as a small
      JSON file; any tool that works file-to-file can be a step
- [ ] Batch window: add files or a folder, build the recipe, choose the output
      folder and file naming, run with progress and a per-file report
- [ ] Save, rename, import and export recipes; a few built in, such as "Scan
      clean-up" (OCR, then compress)
- [ ] One failed file never stops the batch, and originals are never modified

### Later (1–2 weekends each unless noted)

- Compare two PDFs
- Extract text, images and tables
- Convert: PDF to images and back; office documents to PDF (Decision 4)
- Scan to PDF from phone photos (adds an image-processing library of 60 MB or more)
- Read aloud
- Certificate signatures: sign and verify (about 2 weekends)
- Command-line interface (reuses the job processes)
- Flathub release (half a day to a day)
- Offline assistant (3–4 weekends; Decision 5)

---

## 7. Quality and releases

### Tests

| Layer | What it covers | How it runs |
|---|---|---|
| Engine tests | Every PDF operation, on small PDFs generated inside the tests | `./dev test`; plain function calls, milliseconds each |
| Process tests | Requests and replies between interface and engine; recovery when the engine dies | `./dev test` |
| Interface tests | The app starts, opens a file, modes and dialogs work | `./dev test`, on a hidden display |
| Safety tests | Redaction leaves nothing behind; Save never corrupts; undo restores exactly | Part of the engine tests; they block a release if they fail |
| Benchmarks | The budgets below | `./dev bench`, run before each release |
| Manual checklist | The installed snap on a real desktop | Before each promotion to `stable` |

### Performance budgets

| What | Budget |
|---|---|
| Open a 500-page file to first page visible | under 1 second |
| Longest pause of the interface while the engine works | under 20 ms |
| Undo or redo on a file up to 100 MB | under 200 ms |
| Memory used by cached page images | 256 MB by default |
| Download size of the snap at 1.0 | under 100 MB |

### A feature is done when

1. Its tests pass in CI on both Ubuntu versions.
2. It works by keyboard alone and in dark mode.
3. Undo and redo work for every change it makes.
4. Its text is marked for translation.
5. It is listed in the changelog.

### Release steps

1. CI is green on `main`; the `edge` channel already has the build.
2. Run the benchmarks and the manual checklist on the installed `edge` snap.
3. Update the version and the changelog; tag `vX.Y.Z`.
4. Promote `edge` to `stable` in the Snap Store.

---

## 8. Publishing

**Snap Store (Ubuntu App Center), from release 0.1.** Free.

1. Create an Ubuntu One account and run `snapcraft register bluepencil`.
2. Build with `snapcraft`; install the result locally and test it.
3. Upload to the `edge` channel. Review is automatic and takes minutes. A
   manual review is possible for a new name or extra permissions, and takes
   from hours to a few days.
4. Fill in the listing: title `Bluepencil`, a summary of at most 78 characters
   that contains "PDF", description, screenshots, icon, licence, links.
5. Promote to `stable`.

After the first upload, CI repeats steps 2 and 3 on every push.

**Flathub, after 1.0.** Free, and the most widely used app store on other
Linux systems such as Fedora and Linux Mint. Same code, a second packaging
file, submitted as a pull request on GitHub and reviewed by volunteers.

---

## 9. Risks

| Risk | What is done about it |
|---|---|
| A closed or paid edition is wanted later, which the AGPL rules out. | Keep all code owned by the project (contributor licence agreement), keep PyMuPDF inside `core/` so the engine can be replaced, or buy Artifex's commercial licence (Decision 1). |
| PDF work freezes the interface, because Python runs one thing at a time inside a process. | The engine and heavy jobs run in their own processes (D1, D2). Measured pause: 3 ms. A budget in section 7 keeps it that way. |
| A damaged or hostile PDF crashes the PDF library. | Only the engine process dies; the app restarts it and reopens the document from the newest snapshot (D1, D4). The sandbox, with no network access, limits what a hostile file could reach. |
| The sandbox blocks something users expect, such as printing or dragging files in. | Package in Milestone 4, not at the end. Test inside the snap at every release. |
| Redaction leaves recoverable content. | Full-rewrite saves only (D5), a verification pass on every output, and safety tests that block releases. |
| Text editing looks wrong when fonts do not match. | Scope limited to line-level fixes; the user is told when a substitute font is used. |
| Two GTK versions: 4.14 on the development machine, 4.18 in the store build. | The compatibility floor (D8) and CI on both. |
| A new engine version changes behaviour. | Pin the exact version; upgrade deliberately, with the whole test suite. |
| Python's garbage collector cannot see reference cycles that pass through GTK, so windows and their page images could leak. | Handlers on a widget's own children are connected weakly (rule 12), and a test checks that closed windows are freed. |
| One maintainer and a long feature list. | Small releases that each stand alone, the "will not be" list in section 2, and scope guards on the hard features. |
| The name collides with a trademark. | Not checked yet. Check before 1.0, while a rename is still cheap. |

---

## 10. Decisions

| # | Decision | Recommendation or outcome | Needed by |
|---|---|---|---|
| 1 | Open source or private? | **Settled 18 November 2026:** open source, AGPL-3.0-or-later | Done |
| 2 | Snap base: `core24` or the newer `core26`? | `core24`: mature, and its GNOME runtime was checked on this machine | Milestone 4 |
| 3 | Which OCR languages ship in the snap? | English plus a short list chosen then; others can be added as files | Release 1.2 |
| 4 | Office-to-PDF conversion needs LibreOffice, about 300 MB. Bundle it? | No. Leave conversion out until there is a lighter way. | When Convert starts |
| 5 | An offline assistant needs a model of 2–4 GB. How does it arrive without network access? | The user downloads a model file separately and points Bluepencil at it. | When the assistant starts |
| 6 | When does the compatibility floor rise above Ubuntu 22.04? | **Settled 18 November 2026:** raised to Ubuntu 24.04 (GTK 4.14, libadwaita 1.5, Python 3.12) after the development machine was upgraded | Done |

**Decision 1, settled 18 November 2026: open source.** Bluepencil is licensed
under the GNU Affero General Public License, version 3 or later. Its PDF
engine, PyMuPDF, is available under the AGPL or under a paid commercial
licence from its maker, Artifex, and the AGPL requires an app built on it to
publish its own source code under the same terms. The alternative, libraries
without that condition (pypdfium2, pikepdf, pypdf), would have added an
estimated 8–12 weekends before 2.0 and made redaction and text fixes much
harder. What follows from the decision:

- The code is public on GitHub. Anyone may copy, change and redistribute it,
  even sell it, as long as they publish their code under the same licence.
- Income from donations, paid support and custom work for companies stays
  possible. A closed or paid "Pro" edition does not, unless Artifex's
  commercial licence is bought (price only on request) or the engine is
  replaced.
- To keep a later change of licence possible, all code must stay owned by the
  project: outside contributions are accepted only under a contributor
  licence agreement.
- Versions already published stay under the AGPL, whatever happens later.
- `core/` stays the only code that touches PyMuPDF, so the engine can be
  replaced without rewriting the interface.

---

## 11. Development rules

1. Run and test only through `./dev`. A plain `python3 -m bluepencil` can pick
   up the wrong Python or crash on settings leaked by a snap-installed VS Code.
2. `core/` runs inside the engine and job processes and never imports GTK.
   `ui/` never imports the PDF library. The two sides exchange requests and
   plain data, nothing else.
3. Every engine feature ships with tests. Every bug fix starts with a test that
   fails.
4. Nothing newer than GTK 4.14 and libadwaita 1.5 (D8).
5. No network code. No telemetry.
6. Never write to a user's file without an explicit Save. Destructive tools
   default to "Save a copy".
7. Nothing slow runs in the interface process. PDF work goes to the engine;
   long jobs go to a job process.
8. User-visible text goes through the translation function from Milestone 1 on.
9. Every source file starts with the two licence lines:
   `SPDX-FileCopyrightText: <year> <author>` and
   `SPDX-License-Identifier: AGPL-3.0-or-later`.
10. Keep commits small, one change each, with `./dev check` and the tests
    passing.
11. When work lands or a decision is made, update this plan.
12. A widget connects to signals of things it owns (children, controllers,
    adjustments) through `weakly()` from `ui/weak.py`. A plain connection
    there keeps the widget, and everything it holds, alive forever.

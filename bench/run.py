# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Measures Bluepencil against the performance budgets in the plan (section 7).

Run it with `./dev bench`. The sample files are made once, in build/bench/.
The app runs on a hidden display, so the numbers include the cost of drawing
without a graphics card; on a real desktop drawing is usually faster.
The exit status is 1 if any budget is missed.
"""

import argparse
import functools
import os
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Generator
from dataclasses import dataclass
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from bluepencil.application import BluepencilApplication  # noqa: E402
from bluepencil.engine_client import EngineClient  # noqa: E402
from bluepencil.ui.document_view import CACHE_BYTES, DocumentView  # noqa: E402
from bluepencil.ui.thumbnails import ThumbnailSidebar  # noqa: E402
from bluepencil.window import BluepencilWindow  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "build" / "bench"
MB = 1024 * 1024

#: Benchmarks are generators. Each value they yield is a condition, checked
#: every few milliseconds while the app runs; they resume once it is true.
type Steps[T] = Generator[Callable[[], bool], None, T]


@dataclass
class Result:
    what: str
    value: str
    budget: str
    passed: bool | None  # None: measured, but there is no budget for it


#: How long each call of Bluepencil's own main-loop work took, in seconds:
#: handling engine replies (pages arriving), and deciding what to render.
OWN_WORK: list[float] = []


def time_own_work() -> None:
    """Record the duration of every call of the interface's own work."""

    def timed(method: Callable[..., object]) -> Callable[..., object]:
        @functools.wraps(method)
        def wrapper(*args: object, **kwargs: object) -> object:
            start = time.perf_counter()
            try:
                return method(*args, **kwargs)
            finally:
                OWN_WORK.append(time.perf_counter() - start)

        return wrapper

    for cls, name in (
        (EngineClient, "_on_reply"),
        (DocumentView, "_update"),
        (DocumentView, "_refit"),
        (ThumbnailSidebar, "_update"),
    ):
        setattr(cls, name, timed(getattr(cls, name)))


def wait_seconds(seconds: float) -> Callable[[], bool]:
    end = time.monotonic() + seconds
    return lambda: time.monotonic() >= end


def open_window(app: Gtk.Application, path: Path) -> Steps[BluepencilWindow]:
    window = BluepencilWindow(application=app)
    window.set_default_size(1000, 760)
    window.present()
    yield window.get_mapped
    yield wait_seconds(0.3)  # let the empty window settle first
    window.open_file(Gio.File.new_for_path(str(path)))
    yield lambda: window.view is not None and window.view.pages[window.view.current_page].texture is not None
    yield wait_seconds(0.5)
    return window


def time_to_first_page(app: Gtk.Application, path: Path) -> Steps[float]:
    """Seconds from asking to open `path` to a frame that shows its first page.

    Each run has a new window and so a new engine process, as when a file is
    opened from the file manager.
    """
    window = BluepencilWindow(application=app)
    window.set_default_size(1000, 760)
    window.present()
    yield window.get_mapped
    yield wait_seconds(0.3)
    painted: list[float] = []

    def after_paint(_clock: object) -> None:
        if not painted and window.view is not None and window.view.pages[0].texture is not None:
            painted.append(time.perf_counter())

    clock = window.get_frame_clock()
    handler = clock.connect("after-paint", after_paint)
    start = time.perf_counter()
    window.open_file(Gio.File.new_for_path(str(path)))
    yield lambda: bool(painted)
    clock.disconnect(handler)
    window.close()
    return painted[0] - start


@dataclass
class ScrollReport:
    longest_pause: float
    slow_beats: float  # 99th percentile of the gaps between heartbeats
    longest_own_work: float
    longest_frame: float
    median_frame: float
    peak_image_bytes: int
    pages: int
    seconds: float


def scroll_through(
    app: Gtk.Application, path: Path, pages: int, step: int, zoom: float | None = None
) -> Steps[ScrollReport]:
    """Scroll down `pages` pages, `step` pixels per frame, and watch the interface.

    A high-priority heartbeat runs every millisecond. The longest gap between
    two beats is the longest time the interface could not respond.
    """
    window = yield from open_window(app, path)
    view = window.view
    assert view is not None
    view.go_to_page(0)  # the file may have been left further down by an earlier run
    if zoom is not None:
        view.set_zoom(zoom)
    yield wait_seconds(1.0)
    adjustment = view._scroller.get_vadjustment()
    target = view._page_offsets()[min(pages, view.page_count - 1)]
    gaps: list[float] = []
    last = time.perf_counter()
    peak = 0
    frames: list[float] = []
    frame_start = 0.0

    def before_paint(_clock: object) -> None:
        nonlocal frame_start
        frame_start = time.perf_counter()

    def after_paint(_clock: object) -> None:
        if frame_start:
            frames.append(time.perf_counter() - frame_start)

    clock = window.get_frame_clock()
    handlers = [clock.connect("before-paint", before_paint), clock.connect("after-paint", after_paint)]
    OWN_WORK.clear()

    def beat() -> bool:
        nonlocal last
        now = time.perf_counter()
        gaps.append(now - last)
        last = now
        return GLib.SOURCE_CONTINUE

    def scroll(_widget: Gtk.Widget, _clock: object) -> bool:
        nonlocal peak
        adjustment.set_value(min(adjustment.get_value() + step, target))
        peak = max(peak, sum(page.texture_bytes for page in view.pages))
        return GLib.SOURCE_CONTINUE if adjustment.get_value() < target - 1 else GLib.SOURCE_REMOVE

    beats = GLib.timeout_add(1, beat, priority=GLib.PRIORITY_HIGH)
    started = time.perf_counter()
    view.add_tick_callback(scroll)
    yield lambda: adjustment.get_value() >= target - 1
    seconds = time.perf_counter() - started
    yield wait_seconds(1.0)  # the last pages arrive while the heartbeat still runs
    GLib.source_remove(beats)
    for handler in handlers:
        clock.disconnect(handler)
    peak = max(peak, sum(page.texture_bytes for page in view.pages))
    window.close()
    gaps.sort()
    return ScrollReport(
        longest_pause=gaps[-1],
        slow_beats=gaps[int(len(gaps) * 0.99)],
        longest_own_work=max(OWN_WORK, default=0.0),
        longest_frame=max(frames, default=0.0),
        median_frame=statistics.median(frames) if frames else 0.0,
        peak_image_bytes=peak,
        pages=pages,
        seconds=seconds,
    )


def memory_of(pid: int | None) -> int:
    """Resident memory of a process, in bytes."""
    if pid is None:
        return 0
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    return 0


def run_benchmarks(app: Gtk.Application, results: list[Result], quick: bool) -> Steps[None]:
    text, scan = SAMPLES / "text-500.pdf", SAMPLES / "scan-300dpi.pdf"

    times = []
    for _run in range(3 if quick else 5):
        seconds = yield from time_to_first_page(app, text)
        times.append(seconds)
        print(f"  open to first page: {seconds:.2f} s", flush=True)
    worst = max(times)
    results.append(
        Result(
            "Open a 500-page file, first page visible",
            f"{statistics.median(times):.2f} s median, {worst:.2f} s worst of {len(times)}",
            "under 1 s",
            worst < 1.0,
        )
    )

    for label, path, pages, zoom in (
        ("text pages", text, 40 if quick else 120, None),
        ("300-dpi scans", scan, 12 if quick else 29, None),
        ("text pages at 200 %", text, 40 if quick else 100, 2.0),
    ):
        report = yield from scroll_through(app, path, pages, step=150, zoom=zoom)
        print(f"  scrolled {report.pages} {label} in {report.seconds:.1f} s", flush=True)
        results.append(
            Result(
                f"Longest pause for Bluepencil's own work, scrolling {label}",
                f"{report.longest_own_work * 1000:.1f} ms",
                "under 20 ms",
                report.longest_own_work < 0.020,
            )
        )
        results.append(
            Result(
                f"  Drawing one frame, scrolling {label}",
                f"{report.median_frame * 1000:.0f} ms median, {report.longest_frame * 1000:.0f} ms longest",
                "",
                None,
            )
        )
        results.append(
            Result(
                f"  Longest pause of any kind, scrolling {label}",
                f"{report.longest_pause * 1000:.0f} ms (99 % under {report.slow_beats * 1000:.0f} ms)",
                "",
                None,
            )
        )
        if zoom is not None:
            results.append(
                Result(
                    f"Page images in memory, scrolling {label}",
                    f"{report.peak_image_bytes / MB:.0f} MB at most",
                    f"{CACHE_BYTES // MB} MB",
                    report.peak_image_bytes <= CACHE_BYTES,
                )
            )

    window = yield from open_window(app, text)
    engine = window._engine
    interface, engine_memory = memory_of(os.getpid()), memory_of(engine.pid if engine else None)
    results.append(
        Result(
            "Memory of the interface and the engine, one file open",
            f"{interface / MB:.0f} MB and {engine_memory / MB:.0f} MB",
            "",
            None,
        )
    )
    window.close()
    results.append(Result("Undo or redo on a file up to 100 MB", "not built yet", "under 200 ms", None))
    return None


class BenchApplication(BluepencilApplication):
    def do_activate(self) -> None:
        pass  # no window of its own: each benchmark opens the windows it needs


def drive(benchmarks: Callable[[Gtk.Application], Steps[None]], timeout: float) -> None:
    """Run `benchmarks` inside the app's main loop."""
    app = BenchApplication()
    # Never hand off to a copy of Bluepencil that is already open.
    app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
    steps = benchmarks(app)
    errors: list[BaseException] = []
    deadline = time.monotonic() + timeout
    condition: list[Callable[[], bool]] = []

    def tick() -> bool:
        try:
            if not condition:
                condition.append(next(steps))
            while condition[0]():
                condition[0] = next(steps)
            if time.monotonic() > deadline:
                raise TimeoutError(f"the benchmarks took longer than {timeout:.0f} s")
            return GLib.SOURCE_CONTINUE
        except StopIteration:
            pass
        except BaseException as error:  # noqa: BLE001 - reported after the app quits
            errors.append(error)
        app.quit()
        return GLib.SOURCE_REMOVE

    def on_startup(_app: Gtk.Application) -> None:
        app.hold()  # windows come and go; the app stays until the end
        GLib.timeout_add(2, tick)

    app.connect("startup", on_startup)
    app.run(["bluepencil-bench"])
    if errors:
        raise errors[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--quick", action="store_true", help="fewer runs and pages, for a rough check")
    arguments = parser.parse_args()

    subprocess.run([sys.executable, str(Path(__file__).with_name("samples.py")), str(SAMPLES)], check=True)
    results: list[Result] = []
    time_own_work()
    print("Measuring…", flush=True)
    # A history of its own: every run starts each file at its first page,
    # and the developer's list of recent files stays untouched.
    with tempfile.TemporaryDirectory(prefix="bluepencil-bench-") as state:
        os.environ["XDG_STATE_HOME"] = state
        drive(lambda app: run_benchmarks(app, results, arguments.quick), timeout=600)

    width = max(len(result.what) for result in results)
    print()
    for result in results:
        mark = {True: "pass", False: "MISS", None: "    "}[result.passed]
        budget = f"  (budget: {result.budget})" if result.budget else ""
        print(f"{mark}  {result.what.ljust(width)}  {result.value}{budget}")
    return 1 if any(result.passed is False for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())

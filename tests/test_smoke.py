"""Smoke tests: the app starts, shows its window and reacts to a file.

They need a display; `./dev test` runs them on a hidden one.
"""

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gio, GLib  # noqa: E402

from bluepencil import APP_ID, APP_NAME  # noqa: E402
from bluepencil.application import BluepencilApplication  # noqa: E402
from bluepencil.window import BluepencilWindow  # noqa: E402


def run_app(
    check: Callable[[BluepencilWindow], None], argv: list[str] | None = None
) -> None:
    """Start the app, run `check` on its window, quit, and re-raise failures.

    GTK swallows exceptions raised inside its callbacks, so the failure is
    carried out of the main loop by hand.
    """
    app = BluepencilApplication()
    # Never hand off to a copy of Bluepencil the developer already has open.
    app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
    errors: list[BaseException] = []
    ran: list[bool] = []

    def run_check() -> bool:
        try:
            check(app.props.active_window)
            ran.append(True)
        except BaseException as error:  # noqa: BLE001 - re-raised below
            errors.append(error)
        finally:
            app.quit()
        return GLib.SOURCE_REMOVE

    # Low priority, so the window is created and the file opened first.
    GLib.idle_add(run_check, priority=GLib.PRIORITY_LOW)
    app.run(["bluepencil", *(argv or [])])

    if errors:
        raise errors[0]
    assert ran, "the app quit before the check ran"


def test_app_id_is_valid() -> None:
    assert Gio.Application.id_is_valid(APP_ID)


def test_window_starts_empty() -> None:
    def check(window: BluepencilWindow) -> None:
        assert window.get_title() == APP_NAME
        assert window.current_file is None
        assert window._status.get_title() == "Open a PDF"

    run_app(check)


def test_pdf_from_command_line_is_opened(tmp_path) -> None:
    pdf = tmp_path / "Contract draft.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")

    def check(window: BluepencilWindow) -> None:
        assert window.current_file is not None
        assert window.current_file.get_path() == str(pdf)
        assert window._title.get_subtitle() == "Contract draft.pdf"

    run_app(check, [str(pdf)])


def test_non_pdf_is_rejected(tmp_path) -> None:
    other = tmp_path / "notes.txt"
    other.write_text("hello")

    def check(window: BluepencilWindow) -> None:
        assert window.current_file is None
        assert window._status.get_title() == "Open a PDF"

    run_app(check, [str(other)])

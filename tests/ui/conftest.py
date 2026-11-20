# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixtures for tests that run the interface. They need a display: `./dev test`
provides a hidden one."""

import time

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gio, GLib  # noqa: E402

from bluepencil.application import BluepencilApplication  # noqa: E402

from .helpers import window_state  # noqa: E402


@pytest.fixture
def run_app():
    """Return a function that starts the app and drives it step by step.

    Each step is either a function taking the active window, or a
    (condition, action) pair whose action runs once condition(window) is
    true. The main loop keeps running between steps, so engine replies and
    redraws happen as they would for a user.
    """

    def run(*steps, argv=(), timeout=20.0):
        app = BluepencilApplication()
        # Never hand off to a copy of Bluepencil the developer has open.
        app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        pending = [step if isinstance(step, tuple) else (None, step) for step in steps]
        errors: list[BaseException] = []
        deadline = time.monotonic() + timeout

        def tick() -> bool:
            window = app.props.active_window
            try:
                if pending:
                    condition, action = pending[0]
                    if condition is not None and not (window is not None and condition(window)):
                        if time.monotonic() < deadline:
                            return GLib.SOURCE_CONTINUE
                        name = (condition.__doc__ or condition.__name__).strip()
                        # Which step, and what the window showed instead: a
                        # failure on another system says what went wrong there.
                        step = len(steps) - len(pending) + 1
                        raise AssertionError(
                            f"step {step} of {len(steps)} timed out waiting for: {name}. "
                            f"The window showed {window_state(window)}"
                        )
                    pending.pop(0)
                    action(window)
                    return GLib.SOURCE_CONTINUE
            except BaseException as error:  # noqa: BLE001 - re-raised below
                errors.append(error)
            app.quit()
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(20, tick)
        app.run(["bluepencil", *map(str, argv)])
        if errors:
            raise errors[0]
        assert not pending, "the app stopped before every step ran"

    return run

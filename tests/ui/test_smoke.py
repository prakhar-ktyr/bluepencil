# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Smoke tests: the app starts, shows its window and states its licence."""

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gtk  # noqa: E402

from bluepencil import APP_ID, APP_NAME, COPYRIGHT  # noqa: E402
from bluepencil.application import build_about_dialog  # noqa: E402


def test_app_id_is_valid() -> None:
    assert Gio.Application.id_is_valid(APP_ID)
    # Hyphens are allowed by GLib but not inside a D-Bus name's middle parts,
    # which is how desktops and Flathub use the ID.
    assert "-" not in APP_ID and "USERNAME" not in APP_ID


def test_window_starts_empty(run_app) -> None:
    def check(window) -> None:
        assert window.get_title() == APP_NAME
        assert window.current_file is None and window.view is None
        assert window._status.get_title() == "Open a PDF"

    run_app(check)


def test_about_window_shows_the_licence(run_app) -> None:
    def check(_window) -> None:
        about = build_about_dialog()
        assert about.get_license_type() == Gtk.License.AGPL_3_0
        assert about.get_copyright() == COPYRIGHT
        assert about.get_application_name() == APP_NAME

    run_app(check)

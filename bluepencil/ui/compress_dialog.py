# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Compress dialog: choose how small, see the real result, save a copy.

The open document is never changed: compressing makes a new file, kept in
the cache until the user saves it somewhere (plan, D5).
"""

import secrets
import time
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, GObject, Gtk  # noqa: E402

from ..i18n import _  # noqa: E402
from ..job_client import Job  # noqa: E402
from .weak import weakly  # noqa: E402

#: A result smaller by less than this share is not worth a second file.
MIN_SAVING = 0.02
#: Results nobody saved, left by a crash, are deleted after this many seconds.
STALE_RESULT = 24 * 3600


def _presets() -> list[tuple[str, str, str]]:
    return [
        ("email", _("Email"), _("Smallest. Pictures at 96 dpi, fine on screen.")),
        ("balanced", _("Balanced"), _("Pictures at 150 dpi, good on screen and on paper.")),
        ("print", _("Print"), _("Photos at 300 dpi; other pictures as they are.")),
        ("lossless", _("Lossless"), _("Pictures as they are; only unused data goes.")),
    ]


def _stage_text(stage: str) -> str:
    return {
        "reading": _("Reading"),
        "pictures": _("Shrinking pictures"),
        "fonts": _("Shrinking fonts"),
        "writing": _("Writing"),
        "checking": _("Checking the result"),
        "done": _("Done"),
    }.get(stage, stage)


def _failure_text(code: str | None) -> str:
    return {
        "not-found": _("The document could not be read. Save it, then try again."),
        "needs-password": _("The document’s password is needed."),
        "check-failed": _("The smaller copy did not read back correctly, so it was thrown away."),
    }.get(code or "", _("Compressing did not work. The document is unchanged."))


class CompressDialog(Adw.Dialog):
    """Emits save-requested with the path of the smaller copy."""

    __gtype_name__ = "BluepencilCompressDialog"
    __gsignals__ = {
        "save-requested": (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }

    def __init__(self, source: str, password: str | None, original_size: int, work_folder: Path) -> None:
        super().__init__(title=_("Compress"), content_width=460)
        self._source, self._password, self.original_size = source, password, original_size
        self._work_folder = work_folder
        self._job: Job | None = None
        #: The smaller copy, until it is saved or thrown away.
        self.result_path: str | None = None
        self.result_size = 0
        _remove_stale_results(work_folder)

        group = Adw.PreferencesGroup(
            title=_("How Small?"),
            description=_("Now {size}. You save a smaller copy; this document stays as it is.").format(
                size=GLib.format_size(original_size)
            ),
        )
        self.choices: dict[str, Gtk.CheckButton] = {}
        first: Gtk.CheckButton | None = None
        for key, title, subtitle in _presets():
            check = Gtk.CheckButton(group=first, valign=Gtk.Align.CENTER)
            first = first or check
            row = Adw.ActionRow(title=title, subtitle=subtitle, activatable_widget=check)
            row.add_prefix(check)
            group.add(row)
            check.connect("toggled", weakly(self._on_choice_changed))
            self.choices[key] = check
        self.choices["balanced"].set_active(True)
        self._group = group

        self.compress_button = Gtk.Button(label=_("_Compress"), use_underline=True, halign=Gtk.Align.CENTER)
        self.compress_button.add_css_class("suggested-action")
        self.compress_button.add_css_class("pill")
        self.compress_button.connect("clicked", weakly(self._on_compress_clicked))

        self.progress = Gtk.ProgressBar(show_text=True)
        cancel = Gtk.Button(label=_("C_ancel"), use_underline=True, halign=Gtk.Align.CENTER)
        cancel.add_css_class("pill")
        cancel.connect("clicked", weakly(self._on_cancel_clicked))
        running = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        running.append(self.progress)
        running.append(cancel)

        self.result_label = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.result_label.add_css_class("title-4")
        self.save_button = Gtk.Button(label=_("Save a Copy _As…"), use_underline=True, halign=Gtk.Align.CENTER)
        self.save_button.add_css_class("suggested-action")
        self.save_button.add_css_class("pill")
        self.save_button.connect("clicked", weakly(self._on_save_clicked))
        done = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        done.append(self.result_label)
        done.append(self.save_button)

        self.stage = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stage.add_named(self.compress_button, "choose")
        self.stage.add_named(running, "running")
        self.stage.add_named(done, "done")

        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=24,
            margin_top=12,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
        )
        content.append(group)
        content.append(self.stage)
        view = Adw.ToolbarView(content=content)
        view.add_top_bar(Adw.HeaderBar())
        self.set_child(view)
        self.connect("closed", self._on_closed)

    @property
    def preset(self) -> str:
        return next(key for key, check in self.choices.items() if check.get_active())

    def start(self) -> None:
        """Compress with the chosen preset."""
        self._discard_result()
        self._work_folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = self._work_folder / f"{secrets.token_hex(6)}.pdf"
        job = Job(
            {
                "job": "compress",
                "source": self._source,
                "target": str(target),
                "preset": self.preset,
                "password": self._password,
            }
        )
        job.connect("progress", weakly(self._on_progress))
        job.connect("finished", weakly(self._on_finished))
        self._job = job
        self.progress.set_fraction(0)
        self.progress.set_text(_stage_text("reading"))
        self._group.set_sensitive(False)
        self.stage.set_visible_child_name("running")
        job.start()

    def cancel(self) -> None:
        if self._job is not None:
            self._job.cancel()
            self._job = None
        self._group.set_sensitive(True)
        self.stage.set_visible_child_name("choose")

    def _on_compress_clicked(self, _button: Gtk.Button) -> None:
        self.start()

    def _on_cancel_clicked(self, _button: Gtk.Button) -> None:
        self.cancel()

    def _on_choice_changed(self, check: Gtk.CheckButton) -> None:
        if check.get_active() and self._job is None:
            # Another choice: the size shown so far no longer applies.
            self._discard_result()
            self.stage.set_visible_child_name("choose")

    def _on_progress(self, _job: Job, stage: str, fraction: float) -> None:
        self.progress.set_fraction(fraction)
        self.progress.set_text(_stage_text(stage))

    def _on_finished(self, job: Job, result: dict) -> None:
        self._job = None
        self._group.set_sensitive(True)
        target = job.request["target"]
        if not result.get("ok"):
            self._show_result(_failure_text(result.get("error")), saveable=False)
            return
        size = int(result["size"])
        if size > self.original_size * (1 - MIN_SAVING):
            Path(target).unlink(missing_ok=True)
            self._show_result(_("This setting cannot make the file smaller. Nothing was changed."), saveable=False)
            return
        self.result_path, self.result_size = target, size
        saving = round(100 * (1 - size / self.original_size))
        self._show_result(
            _("{before} → {after}, {saving} % smaller").format(
                before=GLib.format_size(self.original_size), after=GLib.format_size(size), saving=saving
            ),
            saveable=True,
        )

    def _show_result(self, text: str, saveable: bool) -> None:
        self.result_label.set_label(text)
        self.save_button.set_visible(saveable)
        self.stage.set_visible_child_name("done")

    def _on_save_clicked(self, _button: Gtk.Button) -> None:
        if self.result_path is not None:
            self.emit("save-requested", self.result_path)

    def _discard_result(self) -> None:
        if self.result_path is not None:
            Path(self.result_path).unlink(missing_ok=True)
            self.result_path = None

    def _on_closed(self, _dialog: Adw.Dialog) -> None:
        if self._job is not None:
            self._job.cancel()
            self._job = None
        self._discard_result()


def _remove_stale_results(folder: Path) -> None:
    """Results left behind by a crash, never saved."""
    if not folder.is_dir():
        return
    now = time.time()
    for leftover in folder.iterdir():
        try:
            if now - leftover.stat().st_mtime > STALE_RESULT:
                leftover.unlink()
        except OSError:
            continue

# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Translation. Every user-visible string goes through _().

No translations exist yet; until they do, _() returns the English text.
"""

import gettext
from pathlib import Path

_translation = gettext.translation(
    "bluepencil",
    localedir=Path(__file__).resolve().parent / "locale",
    fallback=True,
)
_ = _translation.gettext
ngettext = _translation.ngettext

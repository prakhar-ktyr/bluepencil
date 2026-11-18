# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Entry point: `python3 -m bluepencil [file.pdf]`."""

import sys

from .application import BluepencilApplication


def main() -> int:
    return BluepencilApplication().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())

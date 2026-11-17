"""Entry point: `python3 -m bluepencil [file.pdf]`."""

import sys

from .application import BluepencilApplication


def main() -> int:
    return BluepencilApplication().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())

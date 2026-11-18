# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signal handlers that do not keep their widget alive.

When a widget connects one of its own methods to a signal of something it
owns, such as a child widget, a controller or an adjustment, the reference
cycle runs through GTK, where Python's garbage collector cannot see it. The
widget would then never be freed, nor anything it holds, such as rendered
pages: every closed window stayed in memory. Connecting through weakly()
leaves no cycle.
"""

import weakref
from collections.abc import Callable
from typing import Any


def weakly(method: Callable[..., Any]) -> Callable[..., Any]:
    """A handler that calls the bound `method` for as long as its object lives."""
    reference = weakref.WeakMethod(method)

    def handler(*args: object) -> Any:
        bound = reference()
        return bound(*args) if bound is not None else None

    return handler

# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signal handlers that do not keep their widget alive.

When a widget connects one of its own methods to a signal of something it
owns, such as a child widget, a controller or an adjustment, the reference
cycle runs through GTK, where Python's garbage collector cannot see it. The
widget would then never be freed, nor anything it holds, such as rendered
pages: every closed window stayed in memory. Connecting through weakly()
leaves no cycle.

The weak reference is to the GObject, not to its Python wrapper. Since
PyGObject 3.55 a wrapper can be dropped while its object lives on, and a
new one, with the same attributes, stands in for it later: a Python weak
reference to the first wrapper would go dead with the widget still on
screen, and its handlers would quietly stop.
"""

import weakref
from collections.abc import Callable
from typing import Any

from gi.repository import GObject


def weakly(method: Callable[..., Any]) -> Callable[..., Any]:
    """A handler that calls the bound `method` for as long as its object lives."""
    owner = getattr(method, "__self__", None)
    function = getattr(method, "__func__", None)
    if owner is None or function is None:
        raise TypeError(f"weakly() takes a bound method, not {method!r}")
    reference: Callable[[], Any] = (
        owner.weak_ref() if isinstance(owner, GObject.Object) else weakref.ref(owner)
    )

    def handler(*args: object) -> Any:
        alive = reference()
        return function(alive, *args) if alive is not None else None

    return handler

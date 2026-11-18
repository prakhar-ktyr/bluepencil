# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""PDF logic. Runs inside the engine and job processes, and never imports GTK.

The interface may import only `protocol` and `limits` from here: everything
else loads the PDF library.
"""

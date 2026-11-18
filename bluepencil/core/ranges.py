# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Page ranges as people type them. Plain Python: the interface uses this
too, to check what is typed, so it must never load the PDF library."""


def parse_ranges(text: str, page_count: int) -> list[list[int]]:
    """Page ranges as people type them, such as "1-3, 5, 8-", as lists of
    pages counted from 0. Raises ValueError if any part is not a range of
    pages that exist."""
    groups = []
    for raw in text.replace(";", ",").split(","):
        part = raw.strip().replace("–", "-")
        if not part:
            continue
        first, dash, last = part.partition("-")
        start = int(first) if first.strip() else 1
        end = (int(last) if last.strip() else page_count) if dash else start
        if not 1 <= start <= end <= page_count:
            raise ValueError(part)
        groups.append(list(range(start - 1, end)))
    if not groups:
        raise ValueError(text)
    return groups


def every(n: int, page_count: int) -> list[list[int]]:
    """Groups of `n` pages, the last one possibly shorter."""
    if n < 1:
        raise ValueError(n)
    return [list(range(start, min(start + n, page_count))) for start in range(0, page_count, n)]

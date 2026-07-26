"""
core/text_repair.py — Repair garbled Arabic (mojibake) and normalize tabular data.

On Arabic Windows, when text takes a wrong path (e.g. UTF-8 bytes written/read via
the cp1256 or latin-1 code page), Arabic turns into soup like "ط§ظ„ظ‚ط³ظ…" instead
of "القسم". This module detects that and fixes it — but ONLY when the fix actually
increases the amount of real Arabic, so it never corrupts already-correct text.

Also normalizes loosely-shaped table data (CSV strings, single-column rows) into a
clean 2-D grid, so spreadsheet/table tools always get proper columns.

Public:
    fix_mojibake(text)            -> str
    repair_value(v)               -> any   (fix strings, pass through others)
    normalize_table(rows)         -> list[list]   (split CSV strings into columns)
"""
from __future__ import annotations

import csv
import io


def _arabic_ratio(s: str) -> float:
    if not s:
        return 0.0
    ar = sum(1 for ch in s if "؀" <= ch <= "ۿ" or "ݐ" <= ch <= "ݿ")
    return ar / len(s)


def _looks_garbled(s: str) -> bool:
    # Characteristic markers of UTF-8 misread as cp1256 ("ط","ظ" soup) or
    # as latin-1 ("Ø","Ù","Ã" soup) or the replacement char.
    markers = "طظ�ØÙÃâ€™"
    hits = sum(s.count(c) for c in markers)
    return hits >= 2


def fix_mojibake(text: str) -> str:
    """
    Return a repaired version of `text` if it appears to be mis-encoded Arabic,
    otherwise return it unchanged. Safe to call on any string.
    """
    if not isinstance(text, str) or not text:
        return text
    if not _looks_garbled(text):
        return text

    base = _arabic_ratio(text)
    best = text
    best_ratio = base

    for enc in ("cp1256", "latin-1", "cp1252"):
        try:
            candidate = text.encode(enc).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError, LookupError):
            continue
        r = _arabic_ratio(candidate)
        # Only accept if it meaningfully increases real Arabic content.
        if r > best_ratio + 0.05:
            best, best_ratio = candidate, r

    return best


def repair_value(v):
    """Fix a single cell value (strings only; numbers/None pass through)."""
    if isinstance(v, str):
        return fix_mojibake(v)
    return v


def _split_csv_line(s: str) -> list:
    """Split one delimited string into fields (handles , ; tab)."""
    # pick the delimiter that yields the most fields
    best_fields, best_n = [s], 1
    for delim in (",", ";", "\t", "|"):
        if delim in s:
            try:
                fields = next(csv.reader(io.StringIO(s), delimiter=delim))
            except Exception:
                fields = s.split(delim)
            if len(fields) > best_n:
                best_fields, best_n = [f.strip() for f in fields], len(fields)
    return best_fields


def normalize_table(rows) -> list:
    """
    Coerce loosely-shaped table data into a clean 2-D grid AND repair mojibake.

    Handles:
      • list of dicts                       → header row + value rows
      • list of lists/tuples                → as-is (cells repaired)
      • list of CSV strings                 → each split into columns
      • a single multiline CSV/TSV string   → split into rows & columns
      • single-element rows that are CSV     → split into columns
    Always returns list[list].
    """
    # A single big string → treat as CSV/TSV document
    if isinstance(rows, str):
        lines = [ln for ln in rows.splitlines() if ln.strip()]
        rows = lines

    if not isinstance(rows, (list, tuple)) or not rows:
        return []

    # list of dicts
    if isinstance(rows[0], dict):
        headers = list(rows[0].keys())
        grid = [headers] + [[r.get(h, "") for h in headers] for r in rows]
        return [[repair_value(c) for c in row] for row in grid]

    grid: list = []
    for r in rows:
        if isinstance(r, str):
            grid.append(_split_csv_line(r))
        elif isinstance(r, (list, tuple)):
            # single-element row that is itself a CSV string → split it
            if len(r) == 1 and isinstance(r[0], str) and any(d in r[0] for d in ",;\t|"):
                grid.append(_split_csv_line(r[0]))
            else:
                grid.append(list(r))
        else:
            grid.append([r])

    # repair every cell and pad rows to equal width
    width = max((len(row) for row in grid), default=0)
    out = []
    for row in grid:
        row = [repair_value(c) for c in row]
        if len(row) < width:
            row = row + [""] * (width - len(row))
        out.append(row)
    return out

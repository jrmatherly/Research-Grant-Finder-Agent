from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

def picked_option(selection: Mapping[str, Any] | None, options: Sequence[str]) -> str | None:
    cells = ((selection or {}).get("selection") or {}).get("cells") or []
    row = cells[0][0] if cells else None
    return options[row] if row is not None and 0 <= row < len(options) else None

def selection_for(selection: Mapping[str, Any] | None, options: Sequence[str], chosen: str | None) -> dict[str, Any] | None:
    """The selection that puts the table's highlight on the row Details shows, or None when it is there already."""
    # The Details selector falls back to its first option when its choice is no longer in the list.
    row = options.index(chosen) if chosen in options else 0 if options else None
    cells = ((selection or {}).get("selection") or {}).get("cells") or []
    if (cells[0][0] if cells else None) == row:
        return None
    return {"selection": {"rows": [], "columns": [], "cells": [] if row is None else [(row, "Title")]}}

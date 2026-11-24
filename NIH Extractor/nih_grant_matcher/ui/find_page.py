from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

def picked_option(selection: Mapping[str, Any] | None, options: Sequence[str]) -> str | None:
    cells = ((selection or {}).get("selection") or {}).get("cells") or []
    row = cells[0][0] if cells else None
    return options[row] if row is not None and 0 <= row < len(options) else None

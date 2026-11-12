"""Shared list-response helper: every list endpoint returns {items, total}."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def paginated(items: Iterable[Any], total: int | None = None) -> dict[str, Any]:
    items = list(items)
    return {"items": items, "total": len(items) if total is None else total}

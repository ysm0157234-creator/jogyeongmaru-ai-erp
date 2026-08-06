from __future__ import annotations

from typing import Any


def sanitize_postgres_text(value: Any) -> Any:
    """Remove NUL characters rejected by PostgreSQL text columns."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [sanitize_postgres_text(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_postgres_text(item) for item in value)
    if isinstance(value, dict):
        return {
            sanitize_postgres_text(key): sanitize_postgres_text(item)
            for key, item in value.items()
        }
    return value

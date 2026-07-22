from __future__ import annotations

import base64
import json
from typing import Any

from api.errors import invalid_argument


def encode_page_token(last_sort: float, offset: int, extra: dict[str, Any] | None = None) -> str:
    payload = {"s": last_sort, "o": offset}
    if extra:
        payload["x"] = extra
    raw = json.dumps(payload, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_page_token(token: str | None) -> tuple[float, int, dict[str, Any] | None]:
    if not token:
        return 0.0, 0, None
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        payload = json.loads(raw)
        return payload.get("s", 0.0), payload.get("o", 0), payload.get("x")
    except (ValueError, json.JSONDecodeError, Exception):
        raise invalid_argument("Invalid page_token")

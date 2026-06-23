from __future__ import annotations

import json
from typing import Iterable


def parse_json_payload(raw_payload: str):
    payload = raw_payload.strip()
    if payload.startswith("```"):
        payload = payload.strip("`")
        if payload.startswith("json"):
            payload = payload[4:]
    return json.loads(payload.strip())


def chunked(items: list, size: int) -> Iterable[list]:
    for start in range(0, len(items), size):
        yield items[start : start + size]

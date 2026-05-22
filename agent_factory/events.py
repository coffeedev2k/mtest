from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def append_event(path: Path, event_type: str, payload: dict[str, Any]) -> None:
    event = {
        "type": event_type,
        "time": now(),
        "payload": payload,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()

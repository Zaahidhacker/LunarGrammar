"""Recent-corrections history (round 2).

In-memory only, bounded, never written to disk by default: each entry
keeps the original text, the corrected text, the mode, the app and a
timestamp. Re-applying an entry goes through the same verification as
undo, so a stale entry can never paste into the wrong place.
"""

import threading
import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CorrectionRecord:
    original: str
    corrected: str
    mode: str
    app: str
    timestamp: float = field(default_factory=time.time)


class CorrectionHistory:
    """Thread-safe bounded history of successful corrections."""

    def __init__(self, max_items: int = 20):
        if max_items < 0:
            raise ValueError("max_items must be >= 0")
        self._max_items = max_items
        self._lock = threading.Lock()
        self._items: list[CorrectionRecord] = []

    def record(self, original: str, corrected: str, mode: str, app: str = "") -> CorrectionRecord | None:
        if self._max_items == 0 or not original or not corrected:
            return None
        entry = CorrectionRecord(original, corrected, mode, app or "")
        with self._lock:
            self._items.append(entry)
            del self._items[: max(0, len(self._items) - self._max_items)]
        return entry

    def list(self) -> list[CorrectionRecord]:
        with self._lock:
            return list(reversed(self._items))

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def set_max_items(self, max_items: int) -> None:
        if max_items < 0:
            raise ValueError("max_items must be >= 0")
        with self._lock:
            self._max_items = max_items
            del self._items[: max(0, len(self._items) - self._max_items)]

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


# Process-wide history used by the live correction path.
HISTORY = CorrectionHistory()

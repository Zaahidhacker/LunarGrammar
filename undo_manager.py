"""Thread-safe undo manager and word-level text diff engine for Luna Grammar."""

import collections
import difflib
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union


class DiffSpan(dict):
    """Visual diff span indicating tag ('equal', 'insert', 'delete') and text."""
    def __init__(self, tag: str, text: str):
        super().__init__(tag=tag, text=text)
        self.__dict__ = self


class TextDiff(dict):
    """Dictionary holding diff statistics and spans with attribute access."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.__dict__ = self


def compute_text_diff(original_text: str, refined_text: str) -> TextDiff:
    """Compute word-level diff and token-level changes between original and refined text.

    Returns a TextDiff object (dict with attribute access) containing:
      - words_added: count of added words (non-whitespace tokens)
      - words_removed: count of removed words (non-whitespace tokens)
      - chars_added: character delta of added tokens
      - chars_removed: character delta of removed tokens
      - net_word_delta: words_added - words_removed
      - net_char_delta: len(refined) - len(original)
      - summary: concise badge string like "+2 / -1 words", "+3 words", or "No changes"
      - spans: list of DiffSpan objects for visual inspection/rendering
      - tokens_added: list of added word tokens
      - tokens_removed: list of removed word tokens
    """
    if not isinstance(original_text, str):
        original_text = str(original_text) if original_text is not None else ""
    if not isinstance(refined_text, str):
        refined_text = str(refined_text) if refined_text is not None else ""

    # Tokenize preserving exact whitespace formatting
    orig_tokens = re.findall(r'\S+|\s+', original_text)
    ref_tokens = re.findall(r'\S+|\s+', refined_text)

    matcher = difflib.SequenceMatcher(None, orig_tokens, ref_tokens)
    spans: List[DiffSpan] = []
    tokens_added: List[str] = []
    tokens_removed: List[str] = []
    words_added = 0
    words_removed = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            chunk = "".join(orig_tokens[i1:i2])
            if chunk:
                spans.append(DiffSpan('equal', chunk))
        elif tag == 'delete':
            chunk = "".join(orig_tokens[i1:i2])
            if chunk:
                spans.append(DiffSpan('delete', chunk))
                for token in orig_tokens[i1:i2]:
                    if not token.isspace():
                        words_removed += 1
                        tokens_removed.append(token)
        elif tag == 'insert':
            chunk = "".join(ref_tokens[j1:j2])
            if chunk:
                spans.append(DiffSpan('insert', chunk))
                for token in ref_tokens[j1:j2]:
                    if not token.isspace():
                        words_added += 1
                        tokens_added.append(token)
        elif tag == 'replace':
            del_chunk = "".join(orig_tokens[i1:i2])
            ins_chunk = "".join(ref_tokens[j1:j2])
            if del_chunk:
                spans.append(DiffSpan('delete', del_chunk))
                for token in orig_tokens[i1:i2]:
                    if not token.isspace():
                        words_removed += 1
                        tokens_removed.append(token)
            if ins_chunk:
                spans.append(DiffSpan('insert', ins_chunk))
                for token in ref_tokens[j1:j2]:
                    if not token.isspace():
                        words_added += 1
                        tokens_added.append(token)

    chars_added = sum(len(t) for t in tokens_added)
    chars_removed = sum(len(t) for t in tokens_removed)
    net_word_delta = words_added - words_removed
    net_char_delta = len(refined_text) - len(original_text)

    if words_added == 0 and words_removed == 0:
        summary = "No changes"
    elif words_added > 0 and words_removed > 0:
        summary = f"+{words_added} / -{words_removed} words"
    elif words_added > 0:
        summary = f"+{words_added} words"
    else:
        summary = f"-{words_removed} words"

    return TextDiff(
        original=original_text,
        refined=refined_text,
        words_added=words_added,
        words_removed=words_removed,
        chars_added=chars_added,
        chars_removed=chars_removed,
        net_word_delta=net_word_delta,
        net_char_delta=net_char_delta,
        summary=summary,
        spans=spans,
        tokens_added=tokens_added,
        tokens_removed=tokens_removed,
    )


class UndoRecord:
    """Immutable representation of a recorded text replacement."""

    def __init__(
        self,
        timestamp: float,
        target_pid: int,
        original_text: str,
        refined_text: str,
        mode_id: Any,
        word_diff: Optional[TextDiff] = None,
    ):
        self.timestamp = timestamp
        self.target_pid = target_pid
        self.original_text = original_text
        self.refined_text = refined_text
        self.mode_id = mode_id
        self.word_diff = word_diff if word_diff is not None else compute_text_diff(original_text, refined_text)

    @property
    def diff(self) -> TextDiff:
        return self.word_diff

    def as_tuple(self) -> Tuple[float, int, str, str, Any]:
        return (self.timestamp, self.target_pid, self.original_text, self.refined_text, self.mode_id)

    def __iter__(self):
        yield self.timestamp
        yield self.target_pid
        yield self.original_text
        yield self.refined_text
        yield self.mode_id

    def __getitem__(self, idx: int):
        return (self.timestamp, self.target_pid, self.original_text, self.refined_text, self.mode_id)[idx]

    def __len__(self) -> int:
        return 5

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, UndoRecord):
            return self.as_tuple() == other.as_tuple()
        if isinstance(other, (tuple, list)) and len(other) == 5:
            return self.as_tuple() == tuple(other)
        return False

    def __repr__(self) -> str:
        return (
            f"UndoRecord(timestamp={self.timestamp:.2f}, target_pid={self.target_pid}, "
            f"mode_id={self.mode_id!r}, original_len={len(self.original_text)}, "
            f"refined_len={len(self.refined_text)})"
        )


class UndoManager:
    """Thread-safe singleton managing replacement history and multi-app undo states."""

    _instance: Optional['UndoManager'] = None
    _singleton_lock = threading.RLock()

    def __new__(cls, *args, **kwargs):
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    @classmethod
    def get_instance(cls, max_history: int = 100) -> 'UndoManager':
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls(max_history=max_history)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Testing utility to completely reset the singleton instance."""
        with cls._singleton_lock:
            if cls._instance is not None:
                cls._instance.clear()
            cls._instance = None

    def __init__(self, max_history: int = 100):
        with self._singleton_lock:
            if getattr(self, '_initialized', False):
                return
            self._lock = threading.RLock()
            self._max_history = max_history
            self._history: collections.deque[UndoRecord] = collections.deque(maxlen=max_history)
            self._pid_history: Dict[int, collections.deque[UndoRecord]] = collections.defaultdict(
                lambda: collections.deque(maxlen=max_history)
            )
            self._initialized = True

    def record_replacement(
        self,
        target_pid: Optional[int],
        original_text: str,
        refined_text: str,
        mode_id: Any = 0,
    ) -> UndoRecord:
        """Record a newly applied text replacement into history."""
        with self._lock:
            pid = target_pid if target_pid is not None else 0
            record = UndoRecord(
                timestamp=time.time(),
                target_pid=pid,
                original_text=original_text,
                refined_text=refined_text,
                mode_id=mode_id,
            )
            self._history.append(record)
            self._pid_history[pid].append(record)
            return record

    def get_last_undo(self, target_pid: Optional[int] = None) -> Optional[UndoRecord]:
        """Retrieve and remove (pop) the most recent replacement for target_pid (or overall)."""
        with self._lock:
            if target_pid is not None:
                pid_queue = self._pid_history.get(target_pid)
                if not pid_queue:
                    return None
                record = pid_queue.pop()
                try:
                    self._history.remove(record)
                except ValueError:
                    pass
                return record

            if not self._history:
                return None
            record = self._history.pop()
            if record.target_pid in self._pid_history:
                try:
                    self._pid_history[record.target_pid].remove(record)
                except ValueError:
                    pass
            return record

    def peek_last(self, target_pid: Optional[int] = None) -> Optional[UndoRecord]:
        """Inspect the most recent replacement without removing it."""
        with self._lock:
            if target_pid is not None:
                pid_queue = self._pid_history.get(target_pid)
                if pid_queue and len(pid_queue) > 0:
                    return pid_queue[-1]
                return None

            if self._history:
                return self._history[-1]
            return None

    def clear(self, target_pid: Optional[int] = None) -> None:
        """Clear replacement history for target_pid, or all history if target_pid is None."""
        with self._lock:
            if target_pid is not None:
                if target_pid in self._pid_history:
                    records_to_remove = list(self._pid_history[target_pid])
                    self._pid_history[target_pid].clear()
                    for r in records_to_remove:
                        try:
                            self._history.remove(r)
                        except ValueError:
                            pass
            else:
                self._history.clear()
                self._pid_history.clear()

    def get_history(self, target_pid: Optional[int] = None) -> List[UndoRecord]:
        """Return a copy of recent records as a list (oldest to newest)."""
        with self._lock:
            if target_pid is not None:
                return list(self._pid_history.get(target_pid, []))
            return list(self._history)

    def count(self, target_pid: Optional[int] = None) -> int:
        """Return number of pending undo records."""
        with self._lock:
            if target_pid is not None:
                return len(self._pid_history.get(target_pid, []))
            return len(self._history)


# --- Global Convenience Functions ---

def get_undo_manager() -> UndoManager:
    return UndoManager.get_instance()


def record_replacement(
    target_pid: Optional[int],
    original_text: str,
    refined_text: str,
    mode_id: Any = 0,
) -> UndoRecord:
    return get_undo_manager().record_replacement(target_pid, original_text, refined_text, mode_id)


def get_last_undo(target_pid: Optional[int] = None) -> Optional[UndoRecord]:
    return get_undo_manager().get_last_undo(target_pid)


def peek_last(target_pid: Optional[int] = None) -> Optional[UndoRecord]:
    return get_undo_manager().peek_last(target_pid)


def clear_history(target_pid: Optional[int] = None) -> None:
    get_undo_manager().clear(target_pid)

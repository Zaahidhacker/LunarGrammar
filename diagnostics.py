"""Operation correlation across the Windows message thread and correction worker."""

import logging
import math
import threading
from collections import defaultdict, deque
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import PureWindowsPath
from time import perf_counter_ns
from traceback import walk_tb
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

operation: ContextVar[str] = ContextVar("luna_operation_id", default="-")
cache_hit: ContextVar[bool] = ContextVar("luna_cache_hit", default=False)


def _compute_percentiles(data: list[float]) -> dict[str, float]:
    """Calculate statistical distribution and percentiles (p50, p90, p95, p99)."""
    if not data:
        return {
            "count": 0,
            "min": 0.0,
            "max": 0.0,
            "mean": 0.0,
            "p50": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "p99": 0.0,
        }
    sorted_data = sorted(data)
    n = len(sorted_data)
    mean_val = sum(sorted_data) / n

    def get_p(p: float) -> float:
        if n == 1:
            return sorted_data[0]
        rank = (p / 100.0) * (n - 1)
        low = int(math.floor(rank))
        high = int(math.ceil(rank))
        if low == high:
            return sorted_data[low]
        weight = rank - low
        return sorted_data[low] * (1.0 - weight) + sorted_data[high] * weight

    return {
        "count": n,
        "min": round(sorted_data[0], 3),
        "max": round(sorted_data[-1], 3),
        "mean": round(mean_val, 3),
        "p50": round(get_p(50), 3),
        "p90": round(get_p(90), 3),
        "p95": round(get_p(95), 3),
        "p99": round(get_p(99), 3),
    }


class DiagnosticsTracker:
    """Thread-safe collector for cache performance, latency percentiles, and throughput."""

    def __init__(self, max_history: int = 10000) -> None:
        self._lock = threading.RLock()
        self._max_history = max_history

        # Cache metrics
        self._cache_hits = 0
        self._cache_misses = 0

        # Latency tracking (per stage and overall)
        self._stage_latencies: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self._max_history)
        )
        self._overall_latencies: deque[float] = deque(maxlen=self._max_history)

        # Throughput metrics
        self._total_input_chars = 0
        self._total_output_chars = 0
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_duration_seconds = 0.0

    def record_cache(self, hit: bool) -> None:
        """Record a cache hit (True) or cache miss (False)."""
        with self._lock:
            if hit:
                self._cache_hits += 1
            else:
                self._cache_misses += 1

    def record_cache_hit(self) -> None:
        """Record a cache hit."""
        self.record_cache(True)

    def record_cache_miss(self) -> None:
        """Record a cache miss."""
        self.record_cache(False)

    def get_cache_stats(self) -> dict[str, Any]:
        """Return cache hit/miss counts, total queries, and hit ratio."""
        with self._lock:
            total = self._cache_hits + self._cache_misses
            ratio = (self._cache_hits / total) if total > 0 else 0.0
            return {
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "total": total,
                "hit_ratio": round(ratio, 4),
            }

    def record_latency(self, stage: str, elapsed_ms: float) -> None:
        """Record execution latency for a stage and overall pipeline."""
        with self._lock:
            self._stage_latencies[stage].append(elapsed_ms)
            self._overall_latencies.append(elapsed_ms)

    def get_latency_percentiles(self, stage: str | None = None) -> dict[str, float]:
        """Return latency percentiles (p50, p90, p95, p99) for a stage or overall."""
        with self._lock:
            if stage is not None:
                data = list(self._stage_latencies.get(stage, []))
            else:
                data = list(self._overall_latencies)
            return _compute_percentiles(data)

    def get_all_stage_percentiles(self) -> dict[str, dict[str, float]]:
        """Return latency percentiles broken down by each stage."""
        with self._lock:
            result = {
                stage: _compute_percentiles(list(latencies))
                for stage, latencies in self._stage_latencies.items()
            }
            result["_overall"] = _compute_percentiles(list(self._overall_latencies))
            return result

    def record_throughput(
        self,
        chars: int = 0,
        tokens: int = 0,
        duration_seconds: float = 0.0,
    ) -> None:
        """Record processed characters, tokens, and duration for throughput tracking."""
        with self._lock:
            if chars > 0:
                self._total_input_chars += chars
            if tokens > 0:
                self._total_input_tokens += tokens
            if duration_seconds > 0.0:
                self._total_duration_seconds += duration_seconds

    def record_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Record input and output token counts."""
        with self._lock:
            self._total_input_tokens += max(0, input_tokens)
            self._total_output_tokens += max(0, output_tokens)

    def record_characters(self, input_chars: int, output_chars: int) -> None:
        """Record input and output character counts."""
        with self._lock:
            self._total_input_chars += max(0, input_chars)
            self._total_output_chars += max(0, output_chars)

    def get_throughput_stats(self) -> dict[str, float]:
        """Return token and character counts alongside processing rates."""
        with self._lock:
            total_chars = self._total_input_chars + self._total_output_chars
            total_tokens = self._total_input_tokens + self._total_output_tokens
            dur = self._total_duration_seconds
            cps = (total_chars / dur) if dur > 0 else 0.0
            tps = (total_tokens / dur) if dur > 0 else 0.0
            return {
                "input_chars": self._total_input_chars,
                "output_chars": self._total_output_chars,
                "total_chars": total_chars,
                "input_tokens": self._total_input_tokens,
                "output_tokens": self._total_output_tokens,
                "total_tokens": total_tokens,
                "total_duration_seconds": round(dur, 4),
                "chars_per_second": round(cps, 2),
                "tokens_per_second": round(tps, 2),
            }

    def get_summary(self) -> dict[str, Any]:
        """Return combined diagnostics summary: cache, latency percentiles, throughput."""
        return {
            "cache": self.get_cache_stats(),
            "latency": self.get_latency_percentiles(),
            "throughput": self.get_throughput_stats(),
        }

    def reset(self) -> None:
        """Reset all recorded metrics."""
        with self._lock:
            self._cache_hits = 0
            self._cache_misses = 0
            self._stage_latencies.clear()
            self._overall_latencies.clear()
            self._total_input_chars = 0
            self._total_output_chars = 0
            self._total_input_tokens = 0
            self._total_output_tokens = 0
            self._total_duration_seconds = 0.0


# Module-level singleton collector
_tracker = DiagnosticsTracker()


def mark_cache_hit(hit: bool = True) -> None:
    """Set operation context cache hit flag and update diagnostics counter."""
    cache_hit.set(hit)
    _tracker.record_cache(hit)


def mark_cache_miss() -> None:
    """Set operation context cache hit flag to False and record cache miss."""
    mark_cache_hit(False)


def is_cache_hit() -> bool:
    """Return whether the current operation context was a cache hit."""
    return cache_hit.get()


def record_cache_hit() -> None:
    """Record a cache hit in the global diagnostics tracker."""
    _tracker.record_cache_hit()


def record_cache_miss() -> None:
    """Record a cache miss in the global diagnostics tracker."""
    _tracker.record_cache_miss()


def record_cache(hit: bool) -> None:
    """Record cache hit or miss in the global diagnostics tracker."""
    _tracker.record_cache(hit)


def get_cache_stats() -> dict[str, Any]:
    """Retrieve cache hit/miss stats and ratio."""
    return _tracker.get_cache_stats()


def record_latency(stage: str, elapsed_ms: float) -> None:
    """Record an execution latency measurement in milliseconds."""
    _tracker.record_latency(stage, elapsed_ms)


def get_latency_percentiles(stage: str | None = None) -> dict[str, float]:
    """Retrieve execution latency percentiles for a stage or overall."""
    return _tracker.get_latency_percentiles(stage)


def get_all_stage_percentiles() -> dict[str, dict[str, float]]:
    """Retrieve latency percentiles broken down for each stage."""
    return _tracker.get_all_stage_percentiles()


def record_throughput(chars: int = 0, tokens: int = 0, duration_seconds: float = 0.0) -> None:
    """Record throughput numbers (characters, tokens, duration)."""
    _tracker.record_throughput(chars, tokens, duration_seconds)


def record_tokens(input_tokens: int, output_tokens: int) -> None:
    """Record input and output tokens."""
    _tracker.record_tokens(input_tokens, output_tokens)


def record_characters(input_chars: int, output_chars: int) -> None:
    """Record input and output character counts."""
    _tracker.record_characters(input_chars, output_chars)


def get_throughput_stats() -> dict[str, float]:
    """Retrieve character and token throughput metrics."""
    return _tracker.get_throughput_stats()


def get_diagnostics_summary() -> dict[str, Any]:
    """Retrieve comprehensive diagnostics summary."""
    return _tracker.get_summary()


def reset_diagnostics() -> None:
    """Reset all diagnostics metrics to initial empty state."""
    _tracker.reset()


def timing(stage: str, started: int) -> None:
    """Only fixed stage names and elapsed time enter diagnostic logs."""
    elapsed_ms = (perf_counter_ns() - started) / 1_000_000
    _tracker.record_latency(stage, elapsed_ms)
    logging.debug("event=timing stage=%s elapsed_ms=%.3f", stage, elapsed_ms)


@contextmanager
def measure(stage: str):
    started = perf_counter_ns()
    try:
        yield
    finally:
        timing(stage, started)


def traced(stage: str):
    def decorate(function: F) -> F:
        @wraps(function)
        def run(*args: Any, **kwargs: Any) -> Any:
            with measure(stage):
                return function(*args, **kwargs)
        return run  # type: ignore[return-value]
    return decorate


def error_frames(error: BaseException) -> str:
    # Frame locations are enough to trace packaged startup failures without
    # logging an exception's message, local variables, or source lines.
    return " > ".join(
        f"{PureWindowsPath(frame.f_code.co_filename).name}:{line}:{frame.f_code.co_name}"
        for frame, line in walk_tb(error.__traceback__)
    )


class OperationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.operation_id = operation.get()
        return True

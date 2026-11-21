"""Independent Responses API requests, LRU caching, and conservative output checks."""

import logging
import math
import re
import threading
from collections import OrderedDict
from contextlib import contextmanager
from time import perf_counter_ns
from typing import Any, Sequence

from config import AppError
from correction_modes import COMMON_INSTRUCTIONS, MODES
import diagnostics
from diagnostics import measure


DEFAULT_MODEL = "gpt-6-luna"

SUPPORTED_MODELS: tuple[str, ...] = (
    "gpt-6-luna",
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-3.5-turbo",
)

MODEL_FALLBACKS: dict[str, list[str]] = {
    "gpt-6-luna": ["gpt-4o-mini", "gpt-4o"],
    "gpt-4o": ["gpt-4o-mini", "gpt-3.5-turbo"],
    "gpt-4o-mini": ["gpt-3.5-turbo"],
    "gpt-3.5-turbo": ["gpt-4o-mini"],
}

DEFAULT_MODEL_TIMEOUTS: dict[str, float] = {
    "gpt-6-luna": 10.0,
    "gpt-4o-mini": 6.0,
    "gpt-4o": 10.0,
    "gpt-3.5-turbo": 8.0,
}


def get_model_fallbacks(model: str) -> list[str]:
    """Return recommended fallback models for the specified model ID."""
    return list(MODEL_FALLBACKS.get(model, ["gpt-4o-mini", "gpt-3.5-turbo"]))


def get_model_timeout(model: str, default: float = 10.0) -> float:
    """Return recommended default timeout in seconds for a model."""
    return DEFAULT_MODEL_TIMEOUTS.get(model, default)


class RefinementCache:
    """Thread-safe in-memory LRU response cache for grammar refinement.

    Keyed on (mode_id, normalized_text) where normalized_text strips leading/trailing
    whitespace. Returns cached refinements instantly (<15ms) while preserving
    requested boundary whitespace and maintaining hit/miss statistics.
    """

    _instance: "RefinementCache | None" = None

    def __init__(self, max_size: int = 1024) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self._max_size = max_size
        self._lock = threading.RLock()
        # Maps (mode_id, normalized_text) -> (core_refined, exact_original, exact_refined)
        self._cache: OrderedDict[tuple[str, str], tuple[str, str, str]] = OrderedDict()
        self._hits = 0
        self._misses = 0

    @classmethod
    def get_instance(cls, max_size: int = 1024) -> "RefinementCache":
        """Return the process-wide default RefinementCache singleton."""
        if cls._instance is None:
            cls._instance = cls(max_size=max_size)
        return cls._instance

    @staticmethod
    def normalize_key(text: str) -> str:
        """Normalize text by stripping leading and trailing whitespace."""
        return text.strip()

    def get(self, mode_id: Any, text: str | None = None) -> str | None:
        """Retrieve a cached refinement result.

        Supports both cache.get(mode_id, text) and cache.get((mode_id, text)).
        Returns None on cache miss. If found, adapts leading/trailing whitespace
        to match the queried text.
        """
        if text is None and isinstance(mode_id, tuple) and len(mode_id) == 2:
            mode_id, text = mode_id
        if text is None:
            return None

        normalized = self.normalize_key(text)
        key = (str(mode_id), normalized)

        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None

            self._hits += 1
            self._cache.move_to_end(key)
            core_refined, exact_orig, exact_refined = self._cache[key]

        # Exact match fast path
        if text == exact_orig:
            return exact_refined

        # Reconstruct boundary whitespace from current query
        leading_ws = text[:len(text) - len(text.lstrip())]
        trailing_ws = text[len(text.rstrip()):] if len(text.rstrip()) < len(text) else ""
        return leading_ws + core_refined + trailing_ws

    def set(self, mode_id: Any, text: str | None = None, result: str | None = None) -> None:
        """Store a refinement result in the cache.

        Supports both cache.set(mode_id, text, result) and cache.set((mode_id, text), result).
        Evicts least recently used items when max_size is exceeded.
        """
        if result is None and isinstance(mode_id, tuple) and len(mode_id) == 2:
            (mode_id, text), result = mode_id, text
        if text is None or result is None:
            return

        normalized = self.normalize_key(text)
        key = (str(mode_id), normalized)
        core_refined = result.strip()

        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (core_refined, text, result)
            if len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def put(self, mode_id: Any, text: str | None = None, result: str | None = None) -> None:
        """Alias for set()."""
        self.set(mode_id, text, result)

    def clear(self, reset_stats: bool = True) -> None:
        """Clear all entries from the cache."""
        with self._lock:
            self._cache.clear()
            if reset_stats:
                self._hits = 0
                self._misses = 0

    def reset_stats(self) -> None:
        """Reset cache hit and miss counters without purging cached entries."""
        with self._lock:
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict[str, Any]:
        """Return cache statistics dictionary: hits, misses, size, max_size, hit_ratio."""
        with self._lock:
            total = self._hits + self._misses
            ratio = (self._hits / total) if total > 0 else 0.0
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._cache),
                "max_size": self._max_size,
                "hit_ratio": round(ratio, 4),
            }

    @property
    def hits(self) -> int:
        with self._lock:
            return self._hits

    @property
    def misses(self) -> int:
        with self._lock:
            return self._misses

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def hit_ratio(self) -> float:
        with self._lock:
            total = self._hits + self._misses
            return round((self._hits / total), 4) if total > 0 else 0.0

    def contains(self, mode_id: Any, text: str) -> bool:
        """Check whether a (mode_id, text) pair exists in the cache."""
        key = (str(mode_id), self.normalize_key(text))
        with self._lock:
            return key in self._cache

    def __contains__(self, item: Any) -> bool:
        if isinstance(item, tuple) and len(item) == 2:
            mode_id, text = item
            return self.contains(mode_id, text)
        return False

    def __len__(self) -> int:
        return self.size

    def __getitem__(self, item: Any) -> str:
        result = self.get(item)
        if result is None:
            raise KeyError(item)
        return result

    def __setitem__(self, item: Any, value: str) -> None:
        self.set(item, value)


_default_cache: RefinementCache | None = None


def get_default_cache(max_size: int = 1024) -> RefinementCache:
    """Return the shared default RefinementCache singleton."""
    global _default_cache
    if _default_cache is None:
        _default_cache = RefinementCache(max_size=max_size)
    return _default_cache


def reset_default_cache() -> None:
    """Reset the shared default RefinementCache singleton."""
    global _default_cache
    if _default_cache is not None:
        _default_cache.clear()


INSTRUCTIONS = COMMON_INSTRUCTIONS + '\n' + MODES['grammar'].instructions

SHORTHAND = {
    "hby": "how about you", "idk": "I don't know", "idc": "I don't care", "imo": "in my opinion",
    "im": "I'm", "ive": "I've", "dont": "don't", "cant": "can't", "wont": "won't",
    "u": "you", "ur": "your or you're", "rn": "right now", "btw": "by the way",
    "tbh": "to be honest", "omw": "on my way", "wyd": "what are you doing",
    "wbu": "what about you", "hru": "how are you", "thx": "thanks", "ty": "thank you",
    "pls": "please", "plz": "please", "bcuz": "because", "becuz": "because",
    "tmrw": "tomorrow", "msg": "message", "smth": "something", "nvm": "never mind",
    "ngl": "not gonna lie", "ik": "I know", "fr": "for real", "lmk": "let me know",
    "brb": "be right back", "asap": "as soon as possible", "fyi": "for your information",
}
CHAT_WORDS = re.compile(r"\b(?:" + "|".join(SHORTHAND) + r")\b", re.I)
CHAT_GUIDANCE = """
Expand clear chat shorthand in context, regardless of case. Preserve ambiguous abbreviations,
names and acronyms. Use grammar to choose your vs. you're for ur. Relevant shorthand: """
MODE_INSTRUCTIONS = {name: COMMON_INSTRUCTIONS + '\n' + mode.instructions
                     for name, mode in MODES.items()}

FENCE = re.compile(r"(?m)^[ \t]*(?:```|~~~)")
COMMENTARY = re.compile(
    r"(?im)^\s*(?:here(?:'s|’s| is| are) (?:the |your |a )?(?:corrected|revised|edited)"
    r"|(?:\*\*)?(?:corrected (?:text|version|sentence)|correction|"
    r"changes made|explanation|suggestion|note)(?:\*\*)?\s*:"
    r"|i (?:can(?:not|'t|’t) (?:help|assist|comply|correct)|made the following changes))"
)
NEWLINES = re.compile(r"\r\n|\r|\n")
URL = re.compile(r"(?i)(?:https?://|www\.)[^\s<>\"\u201c\u201d]+")
DIGITS = re.compile(r"\d+")
SYMBOLS = re.compile(r"[\U0001f000-\U0001faff\u2600-\u27bf\ufe0f\u200d\u20e3]")
MARKUP = re.compile(r"\*\*|__|(?m:^[ \t]*(?:#{1,6} |[-*+] |\d+\. ))")


def urls(value: str) -> list[str]:
    return [url.rstrip(".,;!?") for url in URL.findall(value)]


def validate(original: str, corrected: str, expand_shorthand: bool = False, mode: str = "grammar") -> str:
    if mode not in MODES:
        raise AppError("Unknown correction mode.")
    if not isinstance(corrected, str) or not corrected.strip():
        raise AppError("OpenAI returned an empty correction.")
    if corrected == original:
        return original
    if any(
        char == "\ufffc" or 0xD800 <= ord(char) <= 0xDFFF
        or (ord(char) < 32 and char not in "\t\r\n")
        for char in corrected
    ):
        raise AppError("The correction contained unexpected control characters.")
    extra = 0
    if expand_shorthand:
        extra = sum(len(SHORTHAND[word.lower()]) - len(word) for word in CHAT_WORDS.findall(original)
                    if word.lower() in SHORTHAND)
    level = getattr(MODES[mode], "level", 0)
    allowances = (16, 24, 40, 64, 128, 128)
    ratios = (1.65, 1.9, 2.4, 2.8, 3.5, 3.5)
    allowance = allowances[level] if level < len(allowances) else 128
    ratio = ratios[level] if level < len(ratios) else 3.5

    if len(corrected) > max(len(original) + max(allowance, extra + 8), int(len(original) * ratio)):
        raise AppError("The correction was disproportionately long.")

    if len(original.strip()) >= 40 and len(corrected.strip()) < len(original.strip()) * 0.65:
        raise AppError("The correction appeared truncated.")
    if len(FENCE.findall(corrected)) > len(FENCE.findall(original)):
        raise AppError("The correction introduced a Markdown fence.")
    if len(MARKUP.findall(corrected)) > len(MARKUP.findall(original)):
        raise AppError("The correction introduced Markdown formatting.")
    if len(COMMENTARY.findall(corrected)) > len(COMMENTARY.findall(original)):
        raise AppError("The correction included explanatory text.")
    if urls(original) != urls(corrected):
        raise AppError("The correction changed a URL.")
    if DIGITS.findall(original) != DIGITS.findall(corrected):
        raise AppError("The correction changed numeric details.")
    if SYMBOLS.findall(original) != SYMBOLS.findall(corrected):
        raise AppError("The correction changed an emoji or symbol.")

    original_lines = NEWLINES.split(original)
    corrected_lines = NEWLINES.split(corrected)
    if len(original_lines) != len(corrected_lines):
        raise AppError("The correction changed the line layout.")
    result = []
    for before, after, ending in zip(original_lines, corrected_lines, NEWLINES.findall(original) + [""]):
        if not before.strip():
            if after.strip():
                raise AppError("The correction changed the paragraph layout.")
            result.append(before + ending)
            continue
        core = after.strip(" \t")
        if not core:
            raise AppError("The correction removed a line.")
        if core.startswith(('"', '“', '«', '`')) and core.endswith(('"', '”', '»', '`')):
            if not before.strip().startswith(('"', '“', '«', '`')):
                raise AppError("The correction added a wrapper.")
        leading = before[:len(before) - len(before.lstrip(" \t"))]
        trailing = before[len(before.rstrip(" \t")):]
        result.append(leading + core + trailing + ending)
    return "".join(result)


class GrammarEngine:
    """OpenAI-backed text refinement engine with thread-safe LRU caching and model fallbacks."""

    def __init__(self, settings: Any, key: str, cache: RefinementCache | None = None) -> None:
        try:
            import openai
        except ImportError:
            raise AppError("Install the dependencies with pip install -r requirements.txt.") from None

        # The SDK can enable verbose logging from the environment. Keep it off.
        for name in ("openai", "httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.CRITICAL + 1)
        self.sdk = openai
        self.cache = cache if cache is not None else RefinementCache()
        self.configure(settings)
        self.client = openai.OpenAI(
            api_key=key,
            base_url="https://api.openai.com/v1",
            timeout=self.timeout,
            max_retries=0,
        )

    def close(self) -> None:
        """Close the underlying OpenAI HTTP client."""
        self.client.close()

    def configure(self, settings: Any) -> None:
        """Update runtime parameters from a Settings object."""
        self.model = getattr(settings, "active_model", None) or getattr(settings, "model", DEFAULT_MODEL)
        self.timeout = float(getattr(settings, "timeout_seconds", 10.0))
        self.expand_shorthand = getattr(settings, "expand_shorthand", True)
        self.cache_enabled = getattr(settings, "cache_enabled", True)
        self.fallback_models = getattr(settings, "fallback_models", None)

    def clear_cache(self) -> None:
        """Purge all entries from the engine's cache."""
        self.cache.clear()

    def cache_stats(self) -> dict[str, Any]:
        """Return cache performance statistics."""
        return self.cache.stats()

    @contextmanager
    def request_errors(self):
        """Map raw OpenAI SDK exceptions into structured AppErrors."""
        try:
            yield
        except self.sdk.AuthenticationError:
            raise AppError("OpenAI rejected OPENAI_API_KEY. Check that the key is valid.",
                           "API key rejected", "api.authentication_failed") from None
        except (self.sdk.PermissionDeniedError, self.sdk.NotFoundError):
            raise AppError("OpenAI denied access. Check the project permissions and configured model.",
                           "Model unavailable", "api.model_unavailable") from None
        except self.sdk.RateLimitError as error:
            if error.code in ("insufficient_quota", "billing_hard_limit_reached"):
                raise AppError("OpenAI API quota is exhausted. Check API billing and project limits.",
                               "API quota reached", "api.quota_exhausted") from None
            raise AppError("OpenAI is rate limiting requests. Try again shortly.",
                           "Try again shortly", "api.rate_limited") from None
        except self.sdk.APITimeoutError:
            raise AppError("The OpenAI request timed out.", "Request timed out", "api.timeout") from None
        except self.sdk.APIConnectionError:
            raise AppError("Could not connect to OpenAI. Check your internet connection.",
                           "Connection issue", "api.connection_failed") from None
        except self.sdk.BadRequestError:
            raise AppError("OpenAI rejected the request. Check the model ID and API access.",
                           "Request rejected", "api.request_rejected") from None
        except self.sdk.APIError:
            raise AppError("The OpenAI request failed.", "API unavailable", "api.request_failed") from None

    def check_model(self, model: str | None = None) -> None:
        """Verify model availability using the OpenAI models metadata endpoint."""
        target = model or self.model
        with self.request_errors():
            self.client.models.retrieve(target, timeout=self.timeout)

    def _execute_api_call(
        self,
        selected: str,
        mode: str,
        model: str,
        timeout: float,
    ) -> str:
        """Execute a single API request and validate the returned correction."""
        with measure("api_preparation"):
            if mode not in MODES:
                raise AppError("Unknown correction mode.")
            options = {}
            if model == "gpt-6-luna" or model.startswith("gpt-6-luna-"):
                options = {"reasoning": {"effort": "none"}, "temperature": 0}
            instructions = MODE_INSTRUCTIONS.get(mode)
            if instructions is None:
                instructions = COMMON_INSTRUCTIONS + '\n' + MODES[mode].instructions
            if self.expand_shorthand:
                words = dict.fromkeys(word.lower() for word in CHAT_WORDS.findall(selected))
                if words:
                    instructions += CHAT_GUIDANCE + ', '.join(f'{word}={SHORTHAND[word]}' for word in words)
            else:
                instructions += "\nKeep intentional chat abbreviations unexpanded."
            request = dict(
                model=model,
                input=selected,
                instructions=instructions,
                timeout=timeout,
                store=False,
                max_output_tokens=max(256, len(selected) * 3 + 128),
                **options,
            )

        t_start = perf_counter_ns()
        with self.request_errors(), measure("api_response"):
            response = self.client.responses.create(**request)
        api_duration = (perf_counter_ns() - t_start) / 1_000_000_000

        if response.usage:
            logging.debug(
                'event=api.usage input_tokens=%d output_tokens=%d',
                response.usage.input_tokens,
                response.usage.output_tokens,
            )
            diagnostics.record_tokens(response.usage.input_tokens, response.usage.output_tokens)
            diagnostics.record_throughput(
                chars=len(selected) + len(response.output_text or ""),
                tokens=response.usage.input_tokens + response.usage.output_tokens,
                duration_seconds=api_duration,
            )

        if response.status != "completed":
            raise AppError("OpenAI did not complete the correction.", "Incomplete response", "api.invalid_response")
        if any(
            part.type == "refusal"
            for item in response.output if item.type == "message"
            for part in item.content
        ):
            raise AppError("OpenAI declined to correct the selection.", "Correction declined", "api.invalid_response")

        try:
            with measure("output_validation"):
                validated = validate(selected, response.output_text, self.expand_shorthand, mode)
                diagnostics.record_characters(len(selected), len(validated))
                return validated
        except AppError as error:
            raise AppError(str(error), "Invalid correction", "api.invalid_response") from None

    def correct(
        self,
        selected: str,
        mode: str = "grammar",
        model: str | None = None,
        timeout: float | None = None,
        fallback_models: Sequence[str] | bool | None = None,
    ) -> str:
        """Refine the selected text using the specified correction mode and OpenAI model.

        Checks the thread-safe LRU cache first for instant sub-15ms returns.
        Falls back to secondary models if configured or requested.
        """
        if mode not in MODES:
            raise AppError("Unknown correction mode.")

        # 1. Fast Cache Path (<15ms return without API call)
        t_cache_start = perf_counter_ns()
        if self.cache_enabled and self.cache is not None:
            cached_result = self.cache.get(mode, selected)
            if cached_result is not None:
                diagnostics.mark_cache_hit(True)
                elapsed_ms = (perf_counter_ns() - t_cache_start) / 1_000_000
                diagnostics.record_latency("cache_hit", elapsed_ms)
                diagnostics.record_throughput(
                    chars=len(selected) + len(cached_result),
                    tokens=0,
                    duration_seconds=elapsed_ms / 1000.0,
                )
                logging.debug("event=api.cache_hit mode=%s elapsed_ms=%.3f", mode, elapsed_ms)
                return cached_result

        # Cache Miss
        diagnostics.mark_cache_hit(False)

        # 2. Determine target model and fallback candidate sequence
        primary_model = model or self.model
        effective_timeout = float(timeout) if timeout is not None else self.timeout

        candidates = [primary_model]
        if fallback_models is True:
            candidates.extend(MODEL_FALLBACKS.get(primary_model, ["gpt-4o-mini"]))
        elif isinstance(fallback_models, (list, tuple)):
            for fb in fallback_models:
                if fb not in candidates:
                    candidates.append(fb)
        elif fallback_models is None and self.fallback_models:
            for fb in self.fallback_models:
                if fb not in candidates:
                    candidates.append(fb)

        last_error: AppError | None = None
        for idx, current_model in enumerate(candidates):
            try:
                refined = self._execute_api_call(
                    selected=selected,
                    mode=mode,
                    model=current_model,
                    timeout=effective_timeout,
                )
                # Populate cache on successful refinement
                if self.cache_enabled and self.cache is not None:
                    self.cache.set(mode, selected, refined)
                return refined
            except AppError as err:
                last_error = err
                # Attempt fallback if more candidates remain
                if idx + 1 < len(candidates):
                    logging.warning(
                        "event=api.model_fallback from=%s to=%s error=%s",
                        current_model,
                        candidates[idx + 1],
                        err,
                    )
                    continue
                raise

        if last_error is not None:
            raise last_error
        raise AppError("OpenAI did not return a valid response.", "API failed", "api.request_failed")

    def correct_with_fallback(
        self,
        selected: str,
        mode: str = "grammar",
        model: str | None = None,
        timeout: float | None = None,
        fallback_models: Sequence[str] | bool = True,
    ) -> str:
        """Convenience method to execute refinement with automatic model fallback enabled."""
        return self.correct(
            selected,
            mode=mode,
            model=model,
            timeout=timeout,
            fallback_models=fallback_models,
        )

"""Comprehensive unit tests for Luna's thread-safe RefinementCache and cache diagnostics."""

import threading
import time
import unittest
from unittest.mock import patch

from config import Settings
import diagnostics
from grammar_engine import (
    GrammarEngine,
    RefinementCache,
    get_default_cache,
)


class RefinementCacheCoreTests(unittest.TestCase):
    def setUp(self):
        self.cache = RefinementCache(max_size=5)

    def test_cache_miss_and_hit(self):
        self.assertIsNone(self.cache.get(0, "unknown text"))
        self.assertEqual(self.cache.misses, 1)
        self.assertEqual(self.cache.hits, 0)
        self.assertEqual(self.cache.hit_ratio, 0.0)

        # Set and get
        self.cache.set(0, "i went to store", "I went to the store.")
        res = self.cache.get(0, "i went to store")
        self.assertEqual(res, "I went to the store.")
        self.assertEqual(self.cache.hits, 1)
        self.assertEqual(self.cache.misses, 1)
        self.assertEqual(self.cache.hit_ratio, 0.5)

    def test_whitespace_normalization_and_preservation(self):
        # Cache under clean text
        self.cache.set(0, "hello world", "Hello, world.")

        # Query with leading and trailing whitespace
        query = "   hello world \r\n"
        cached = self.cache.get(0, query)
        self.assertEqual(cached, "   Hello, world. \r\n")

        # Query with tab indentation
        tab_query = "\t\thello world"
        self.assertEqual(self.cache.get(0, tab_query), "\t\tHello, world.")

    def test_mode_isolation(self):
        # Same text refined differently across modes
        self.cache.set(0, "how are you", "How are you?")
        self.cache.set(2, "how are you", "I hope this email finds you well.")

        self.assertEqual(self.cache.get(0, "how are you"), "How are you?")
        self.assertEqual(self.cache.get(2, "how are you"), "I hope this email finds you well.")
        self.assertIsNone(self.cache.get(1, "how are you"))

    def test_tuple_syntax_and_put_alias(self):
        # Support tuple key syntax (mode_id, text)
        self.cache.put((3, "test syntax"), "Test syntax.")
        self.assertEqual(self.cache.get((3, "test syntax")), "Test syntax.")
        self.assertTrue(self.cache.contains(3, "test syntax"))

    def test_lru_eviction(self):
        # max_size is 5
        for i in range(5):
            self.cache.set(0, f"key_{i}", f"val_{i}")
        self.assertEqual(self.cache.size, 5)

        # Access key_0 to make it recently used
        _ = self.cache.get(0, "key_0")

        # Add key_5 - should evict key_1 (oldest untouched)
        self.cache.set(0, "key_5", "val_5")
        self.assertEqual(self.cache.size, 5)
        self.assertIsNone(self.cache.get(0, "key_1"))  # Evicted
        self.assertEqual(self.cache.get(0, "key_0"), "val_0")  # Kept
        self.assertEqual(self.cache.get(0, "key_5"), "val_5")

    def test_clear_and_reset_stats(self):
        self.cache.set(0, "foo", "Foo.")
        self.cache.get(0, "foo")
        self.cache.get(0, "bar")

        stats = self.cache.stats()
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)
        self.assertEqual(stats["size"], 1)
        self.assertEqual(stats["max_size"], 5)

        # Reset stats only
        self.cache.reset_stats()
        self.assertEqual(self.cache.hits, 0)
        self.assertEqual(self.cache.misses, 0)
        self.assertEqual(self.cache.size, 1)

        # Clear cache completely
        self.cache.clear()
        self.assertEqual(self.cache.size, 0)
        self.assertFalse(self.cache.contains(0, "foo"))


class RefinementCacheConcurrencyTests(unittest.TestCase):
    def test_multithreaded_access(self):
        cache = RefinementCache(max_size=50)
        errors = []

        def worker(thread_id):
            try:
                for i in range(100):
                    key = f"thread_{thread_id}_text_{i % 10}"
                    cache.set(0, key, f"Refined {key}")
                    val = cache.get(0, key)
                    self.assertIsNotNone(val)
                    cache.stats()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Thread errors: {errors}")
        self.assertLessEqual(cache.size, 50)


class EngineCacheIntegrationTests(unittest.TestCase):
    def test_engine_instant_cache_hit_without_network(self):
        cache = get_default_cache()
        cache.clear()
        diagnostics.reset_diagnostics()

        text = "this is an uncorrected line"
        expected = "This is an uncorrected line."

        # Instantiate engine with dummy key and mock openai so network call would fail if attempted
        engine = GrammarEngine(Settings(), "dummy_key", cache=cache)
        # Seed with the engine's cache context: a rewrite cached under a
        # different model / shorthand / temperature / prompt must not be reused.
        cache.set("grammar", text, expected, context=engine.cache_context())
        try:
            t0 = time.perf_counter()
            result = engine.correct(text, mode="grammar")
            latency_ms = (time.perf_counter() - t0) * 1000.0

            self.assertEqual(result, expected)
            self.assertLess(latency_ms, 15.0, f"Cache lookup took too long: {latency_ms:.2f} ms")
            self.assertTrue(diagnostics.is_cache_hit())

            # Check cache stats
            stats = engine.cache_stats()
            self.assertGreater(stats["hits"], 0)
        finally:
            engine.close()


if __name__ == '__main__':
    unittest.main()

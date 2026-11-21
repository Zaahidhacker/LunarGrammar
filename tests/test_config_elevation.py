"""Comprehensive unit tests for Luna's elevated configuration system, persistence, migration, and exclusions."""

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from config import (
    AppError,
    Settings,
    auto_migrate_settings,
    load_settings,
    migrate_settings_dict,
    parse_settings,
    read_settings,
    update_settings,
)


class ConfigDefaultsAndSyncTests(unittest.TestCase):
    def test_settings_defaults(self):
        s = Settings()
        self.assertEqual(s.active_model, "gpt-6-luna")
        self.assertEqual(s.model, "gpt-6-luna")
        self.assertTrue(s.cache_enabled)
        self.assertEqual(s.excluded_apps, ())
        self.assertEqual(s.custom_prompt, "")
        self.assertEqual(s.default_mode, 0)
        self.assertTrue(s.show_diff_preview)
        self.assertTrue(s.sound_enabled)
        self.assertEqual(s.temperature, 0.0)

    def test_bidirectional_model_sync(self):
        # Setting model updates active_model
        s1 = Settings(model="gpt-4o-mini")
        self.assertEqual(s1.active_model, "gpt-4o-mini")
        self.assertEqual(s1.model, "gpt-4o-mini")

        # Setting active_model updates model
        s2 = Settings(active_model="gpt-4o")
        self.assertEqual(s2.model, "gpt-4o")
        self.assertEqual(s2.active_model, "gpt-4o")

    def test_to_dict_serialization(self):
        s = Settings(
            active_model="gpt-4o",
            default_mode=2,
            excluded_apps=("calc.exe", "game.exe"),
            cache_enabled=True,
            show_diff_preview=False,
        )
        d = s.to_dict()
        self.assertEqual(d["active_model"], "gpt-4o")
        self.assertEqual(d["model"], "gpt-4o")
        self.assertEqual(d["default_mode"], 2)
        self.assertEqual(d["excluded_apps"], ["calc.exe", "game.exe"])
        self.assertFalse(d["show_diff_preview"])
        self.assertTrue(d["cache_enabled"])


class ConfigMigrationTests(unittest.TestCase):
    def test_migrate_settings_dict_legacy_keys(self):
        legacy = {
            "model": "gpt-4o-mini",
            "theme": "light",
            "sound": False,
        }
        migrated, changed = migrate_settings_dict(legacy)
        self.assertTrue(changed)
        self.assertEqual(migrated["active_model"], "gpt-4o-mini")
        self.assertEqual(migrated["appearance"], "light")
        self.assertEqual(migrated["sound_enabled"], False)
        self.assertNotIn("theme", migrated)
        self.assertNotIn("sound", migrated)

    def test_auto_migrate_settings_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "settings.json"
            path.write_text(json.dumps({"model": "gpt-4o", "theme": "light"}), encoding="utf-8")

            was_migrated = auto_migrate_settings(path)
            self.assertTrue(was_migrated)

            # Reload and check
            loaded = load_settings(path)
            self.assertEqual(loaded.active_model, "gpt-4o")
            self.assertEqual(loaded.appearance, "light")


class ConfigValidationAndExclusionTests(unittest.TestCase):
    def test_valid_exclusion_rules(self):
        data = {
            "excluded_apps": ["Notepad.EXE", "code.exe", "KeePass.exe"],
        }
        settings = parse_settings(data)
        # Should be converted to tuple and lowercased
        self.assertEqual(settings.excluded_apps, ("notepad.exe", "code.exe", "keepass.exe"))

    def test_invalid_exclusion_rules(self):
        invalid_cases = [
            {"excluded_apps": "notepad.exe"},  # not a list
            {"excluded_apps": ["not_an_exe"]},  # does not end with .exe
            {"excluded_apps": ["C:\\Windows\\notepad.exe"]},  # contains path components
            {"excluded_apps": [123]},  # not strings
        ]
        for case in invalid_cases:
            with self.subTest(case=case), self.assertRaises(AppError):
                parse_settings(case)

    def test_default_mode_validation(self):
        # 0 to 5 are valid
        for mode in range(6):
            s = parse_settings({"default_mode": mode})
            self.assertEqual(s.default_mode, mode)

        # Invalid modes
        with self.assertRaises(AppError):
            parse_settings({"default_mode": -1})
        with self.assertRaises(AppError):
            parse_settings({"default_mode": 6})
        with self.assertRaises(AppError):
            parse_settings({"default_mode": "0"})

    def test_temperature_validation(self):
        s1 = parse_settings({"temperature": 0.5})
        self.assertEqual(s1.temperature, 0.5)
        s2 = parse_settings({"temperature": 2.0})
        self.assertEqual(s2.temperature, 2.0)

        with self.assertRaises(AppError):
            parse_settings({"temperature": -0.1})
        with self.assertRaises(AppError):
            parse_settings({"temperature": 2.1})
        with self.assertRaises(AppError):
            parse_settings({"temperature": "1.0"})

    def test_boolean_toggles_validation(self):
        for key in ("cache_enabled", "show_diff_preview", "sound_enabled", "enabled", "feedback"):
            with self.subTest(key=key), self.assertRaises(AppError):
                parse_settings({key: "true"})  # String instead of bool

    def test_model_override_via_env(self):
        with patch.dict(os.environ, {"LUNA_GRAMMAR_MODEL": "gpt-override"}):
            s = parse_settings({"active_model": "gpt-6-luna"})
            self.assertEqual(s.active_model, "gpt-override")
            self.assertEqual(s.model, "gpt-override")


class ConfigPersistenceAndConcurrencyTests(unittest.TestCase):
    def test_update_settings_atomic(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "settings.json"
            update_settings({"active_model": "gpt-4o-mini", "default_mode": 3}, path=path)

            loaded = load_settings(path)
            self.assertEqual(loaded.active_model, "gpt-4o-mini")
            self.assertEqual(loaded.model, "gpt-4o-mini")
            self.assertEqual(loaded.default_mode, 3)

            # Further update
            update_settings({"sound_enabled": False}, path=path)
            reloaded = load_settings(path)
            self.assertFalse(reloaded.sound_enabled)
            self.assertEqual(reloaded.default_mode, 3)

    def test_concurrent_settings_updates(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "settings.json"
            errors = []

            def worker(thread_idx):
                try:
                    for i in range(20):
                        update_settings({
                            "default_mode": i % 6,
                            "custom_prompt": f"worker_{thread_idx}_iteration_{i}",
                        }, path=path)
                        s = load_settings(path)
                        self.assertIsInstance(s.default_mode, int)
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(len(errors), 0, f"Concurrent updates failed: {errors}")


if __name__ == '__main__':
    unittest.main()

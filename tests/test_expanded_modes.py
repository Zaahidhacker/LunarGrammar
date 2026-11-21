"""Comprehensive unit tests for Luna's expanded 6-mode professional catalog."""

import unittest
from correction_modes import (
    COMMON_INSTRUCTIONS,
    MODE_NAMES,
    MODES,
    PRIMARY_MODES,
    CorrectionMode,
    describe_modes,
    get_mode,
    get_mode_by_level,
    get_mode_by_name,
    get_mode_catalog,
    list_modes,
)


class ExpandedModesTests(unittest.TestCase):
    def test_mode_catalog_structure(self):
        """Verify that all 6 modes (0 through 5) are present and properly structured."""
        self.assertEqual(len(PRIMARY_MODES), 6)
        self.assertEqual(len(MODE_NAMES), 6)
        self.assertEqual(MODE_NAMES, ('grammar', 'casual', 'executive', 'academic', 'bulletize', 'translate'))

        for level, key in enumerate(MODE_NAMES):
            mode = PRIMARY_MODES[key]
            self.assertIsInstance(mode, CorrectionMode)
            self.assertEqual(mode.level, level)
            self.assertEqual(mode.key, key)
            self.assertTrue(mode.name)
            self.assertTrue(mode.label)
            self.assertTrue(mode.instructions)
            self.assertTrue(mode.description)
            self.assertTrue(mode.hotkey)
            self.assertTrue(mode.system_prompt)
            self.assertIn(COMMON_INSTRUCTIONS, mode.system_prompt)

    def test_individual_mode_attributes(self):
        """Test specific requirements for each of modes 0 to 5."""
        # Mode 0: Grammar & Spelling
        m0 = get_mode(0)
        self.assertEqual(m0.level, 0)
        self.assertEqual(m0.key, 'grammar')
        self.assertEqual(m0.name, 'Grammar & Spelling')
        self.assertEqual(m0.label, 'Refining…')
        self.assertEqual(m0.hotkey, 'Ctrl+Win+Z')
        self.assertIn("Grammar only", m0.instructions)

        # Mode 1: Casual Polish
        m1 = get_mode(1)
        self.assertEqual(m1.level, 1)
        self.assertEqual(m1.key, 'casual')
        self.assertEqual(m1.name, 'Casual Polish')
        self.assertEqual(m1.label, 'Polishing…')
        self.assertEqual(m1.hotkey, 'Ctrl+Win+1+Z')
        self.assertIn("light polish", m1.instructions)

        # Mode 2: Executive Concise
        m2 = get_mode(2)
        self.assertEqual(m2.level, 2)
        self.assertEqual(m2.key, 'executive')
        self.assertEqual(m2.name, 'Executive Concise')
        self.assertEqual(m2.label, 'Executive…')
        self.assertEqual(m2.hotkey, 'Ctrl+Win+2+Z')
        self.assertIn("business polish", m2.instructions)

        # Mode 3: Academic & Formal
        m3 = get_mode(3)
        self.assertEqual(m3.level, 3)
        self.assertEqual(m3.key, 'academic')
        self.assertEqual(m3.name, 'Academic & Formal')
        self.assertEqual(m3.label, 'Formal…')
        self.assertEqual(m3.hotkey, 'Ctrl+Win+3+Z')
        self.assertIn("maximum refinement", m3.instructions)

        # Mode 4: Bulletize & Summarize
        m4 = get_mode(4)
        self.assertEqual(m4.level, 4)
        self.assertEqual(m4.key, 'bulletize')
        self.assertEqual(m4.name, 'Bulletize & Summarize')
        self.assertEqual(m4.label, 'Bulletizing…')
        self.assertEqual(m4.hotkey, 'Ctrl+Win+4+Z')
        self.assertIn("bullet points", m4.instructions)
        self.assertIn("- ", m4.instructions)

        # Mode 5: Translate to English
        m5 = get_mode(5)
        self.assertEqual(m5.level, 5)
        self.assertEqual(m5.key, 'translate')
        self.assertEqual(m5.name, 'Translate to English')
        self.assertEqual(m5.label, 'Translating…')
        self.assertEqual(m5.hotkey, 'Ctrl+Win+5+Z')
        self.assertIn("Translate to English", m5.instructions)
        self.assertIn("fluent, natural English", m5.description)

    def test_legacy_and_semantic_aliases(self):
        """Verify backward compatibility with earlier 4-mode releases and semantic aliases."""
        self.assertEqual(get_mode('professional_1'), get_mode(1))
        self.assertEqual(get_mode('professional_2'), get_mode(2))
        self.assertEqual(get_mode('professional_3'), get_mode(3))

        self.assertEqual(get_mode('spelling'), get_mode(0))
        self.assertEqual(get_mode('grammar_spelling'), get_mode(0))
        self.assertEqual(get_mode('polish'), get_mode(1))
        self.assertEqual(get_mode('concise'), get_mode(2))
        self.assertEqual(get_mode('formal'), get_mode(3))
        self.assertEqual(get_mode('bullets'), get_mode(4))
        self.assertEqual(get_mode('summarize'), get_mode(4))
        self.assertEqual(get_mode('translation'), get_mode(5))
        self.assertEqual(get_mode('to_english'), get_mode(5))

    def test_lookup_utilities(self):
        """Test get_mode, get_mode_by_level, get_mode_by_name, and string normalization."""
        # By integer level
        for i in range(6):
            self.assertEqual(get_mode_by_level(i).level, i)
            self.assertEqual(get_mode(i).level, i)

        # By string level
        for i in range(6):
            self.assertEqual(get_mode(str(i)).level, i)

        # By key name
        self.assertEqual(get_mode_by_name('bulletize').level, 4)
        self.assertEqual(get_mode('Translate to English').level, 5)
        self.assertEqual(get_mode('Mode 2').level, 2)
        self.assertEqual(get_mode('Level 3').level, 3)

        # Direct identity when passing CorrectionMode
        m = get_mode(0)
        self.assertIs(get_mode(m), m)

    def test_lookup_errors(self):
        """Test error handling for invalid mode queries."""
        with self.assertRaises(KeyError):
            get_mode(6)
        with self.assertRaises(KeyError):
            get_mode(-1)
        with self.assertRaises(KeyError):
            get_mode('non_existent_mode')
        with self.assertRaises(ValueError):
            get_mode_by_level(10)
        with self.assertRaises(ValueError):
            get_mode_by_level(-1)
        with self.assertRaises(TypeError):
            get_mode([1, 2, 3])

    def test_catalog_and_describe_modes(self):
        """Test list_modes, get_mode_catalog, and describe_modes output."""
        modes = list_modes()
        self.assertEqual(len(modes), 6)
        for i, m in enumerate(modes):
            self.assertEqual(m.level, i)

        catalog = get_mode_catalog()
        self.assertEqual(len(catalog), 6)
        for item in catalog:
            self.assertIn('level', item)
            self.assertIn('key', item)
            self.assertIn('name', item)
            self.assertIn('label', item)
            self.assertIn('hotkey', item)
            self.assertIn('instructions', item)
            self.assertIn('system_prompt', item)

        cheatsheet = describe_modes()
        self.assertIn("Luna Professional Correction Modes:", cheatsheet)
        for i in range(6):
            self.assertIn(f"[{i}]", cheatsheet)


if __name__ == '__main__':
    unittest.main()

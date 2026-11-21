import unittest

from pill_art import Motion, pill_position, render, waveform_heights
from correction_modes import MODES


class OverlayTests(unittest.TestCase):
    def test_all_mode_labels_preserve_the_existing_pill_size_and_dismissal(self):
        for mode in MODES.values():
            with self.subTest(level=mode.level):
                motion = Motion()
                motion.begin(0, mode.label)
                for dpi in (96,144,192):
                    frame=motion.sample(.4)
                    self.assertEqual(frame.label,mode.label)
                    self.assertEqual(render(frame,dpi,'dark').size,(round(226*dpi/96),round(54*dpi/96)))
                motion.finish('success','Refined',1)
                self.assertIsNone(motion.sample(2.4))
    def test_waveform_is_smooth_and_uses_distinct_bars(self):
        before, after = waveform_heights(0.6), waveform_heights(0.616)
        self.assertEqual(len(before), 9)
        self.assertGreater(max(before) - min(before), 5)
        self.assertTrue(all(5 <= value <= 18 for value in before))
        self.assertLess(max(abs(a - b) for a, b in zip(before, after)), 1)

    def test_motion_progress_result_fade_and_dismissal(self):
        motion = Motion()
        self.assertIsNone(motion.sample(1))
        motion.begin(2)
        self.assertLess(motion.sample(2.04).opacity, 1)
        self.assertEqual(motion.sample(2.3).opacity, 1)
        motion.finish("success", "Refined", 3)
        self.assertLess(motion.sample(3.09).transition, 1)
        self.assertEqual(motion.sample(3.25).transition, 1)
        self.assertLess(motion.sample(4.2).opacity, 1)
        self.assertIsNone(motion.sample(4.4))
        motion.begin(5)
        motion.dismiss()
        motion.finish("error", "Connection issue", 6)
        self.assertIsNone(motion.sample(6.1))

    def test_reduced_motion_uses_static_waveform_and_immediate_result(self):
        motion = Motion()
        motion.begin(1)
        self.assertEqual(motion.sample(1, True).wave_time, motion.sample(3, True).wave_time)
        self.assertEqual(motion.sample(1, True).opacity, 1)
        motion.finish("error", "Connection issue", 4)
        frame = motion.sample(4, True)
        self.assertEqual((frame.transition, frame.opacity), (1, 1))
        self.assertIsNone(motion.sample(6.3, True))

    def test_render_scales_and_uses_work_area_of_secondary_display(self):
        motion = Motion()
        motion.begin(0)
        frame = motion.sample(0.4)
        normal = render(frame, 96, "dark")
        scaled = render(frame, 144, "light")
        self.assertEqual(normal.size, (226, 54))
        self.assertEqual(scaled.size, (339, 81))
        self.assertEqual(scaled.getpixel((0, 0))[3], 0)
        self.assertEqual(pill_position((-1920, -400, 0, 640), *scaled.size, 144), (-1130, 532))

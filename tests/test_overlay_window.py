import sys
import unittest
from unittest.mock import Mock, patch

if sys.platform == 'win32':
    import overlay
    from pill_art import Motion


@unittest.skipUnless(sys.platform == 'win32', 'Windows only')
class OverlayWindowTests(unittest.TestCase):
    def pill(self):
        pill=object.__new__(overlay.Overlay)
        pill.window=123
        pill.visible=False
        pill.motion=Motion()
        pill.motion.begin(0,'Perfecting…')
        pill.reduce=False
        pill.animation_failed=False
        pill.dismiss_timer=None
        pill.dismiss_generation=0
        return pill

    def test_present_raises_above_other_topmost_windows_without_activating(self):
        pill=self.pill()
        with patch.object(overlay,'set_position',return_value=1) as position:
            pill.present()
        position.assert_called_once_with(123,-1,0,0,0,0,0x0010|0x0001|0x0002|0x0040)
        self.assertTrue(pill.visible)

    def test_animation_failure_preserves_mode_with_an_opaque_static_fallback(self):
        pill=self.pill()
        frames=[]
        def render(now):
            if not pill.reduce:
                raise OSError('fixture animation failure')
            frames.append(pill.motion.sample(now,pill.reduce))
        with patch.object(pill,'tick',side_effect=render), patch.object(overlay,'kill_timer'):
            with self.assertLogs(level='WARNING'):
                pill.paint(.1)
        self.assertTrue(pill.animation_failed)
        self.assertEqual((frames[0].label,frames[0].opacity),('Perfecting…',1))
        self.assertEqual(pill.motion.state,'working')

    def test_windows_timer_failure_falls_back_to_static_working_feedback(self):
        pill=self.pill()
        with patch.object(overlay,'set_timer',return_value=0), patch.object(pill,'paint') as paint:
            with self.assertLogs(level='WARNING'):
                pill.schedule()
        self.assertTrue(pill.reduce)
        self.assertTrue(pill.animation_failed)
        paint.assert_called_once()
        self.assertEqual(pill.motion.state,'working')

    def test_late_fallback_dismiss_cannot_hide_a_new_operation(self):
        pill=self.pill()
        pill.motion.finish('success','Refined',1)
        stale=pill.dismiss_generation
        with patch.object(overlay,'kill_timer'):
            pill.cancel_timers()
            pill.handle_message(123,overlay.WM_DISMISS,stale,0)
        self.assertEqual(pill.motion.state,'success')

    def test_automatic_fallback_dismissal_does_not_suppress_later_feedback(self):
        pill=self.pill()
        pill.motion.finish('success','Refined',1)
        with patch.object(overlay,'kill_timer'):
            pill.handle_message(123,overlay.WM_DISMISS,pill.dismiss_generation,0)
        self.assertFalse(pill.motion.dismissed)
        pill.motion.finish('error','Connection issue',3)
        self.assertEqual(pill.motion.state,'error')

    def test_result_timer_fallback_posts_back_to_the_message_thread(self):
        pill=self.pill()
        pill.reduce=True
        pill.motion.finish('success','Refined',1)
        with patch.object(overlay,'set_timer',return_value=0), patch.object(overlay,'Timer') as timer:
            pill.schedule()
        self.assertEqual(timer.call_args.kwargs['args'],(123,overlay.WM_DISMISS,0,0))
        self.assertTrue(timer.return_value.daemon)
        timer.return_value.start.assert_called_once()


if __name__=='__main__':
    unittest.main()

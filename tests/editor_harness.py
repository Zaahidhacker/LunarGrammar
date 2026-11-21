"""Run the real editor transaction with a synthetic response and a test chord."""

import logging
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import win32 as win
import windows_hotkey as hotkey
from config import AppError, SETTINGS_PATH, load_settings
from diagnostics import OperationFilter

SAMPLE = "i has a luna test"
CORRECTED = "I have a Luna test."


class FixtureEngine:
    def __init__(self, _settings, _key):
        pass

    def configure(self, _settings):
        pass

    def correct(self, selected, mode='grammar'):
        if selected == SAMPLE:
            return {'grammar':CORRECTED, 'professional_1':'I have a Luna test.',
                    'professional_2':'I have a Luna test.', 'professional_3':'I have a Luna test.'}[mode]
        if selected == CORRECTED:
            return selected
        raise AppError("The harness only accepts its exact synthetic selection.",
                       "Select the test sample", "fixture.unexpected_selection")

    def close(self):
        pass


def main():
    console = logging.StreamHandler()
    console.addFilter(OperationFilter())
    logging.basicConfig(level=logging.DEBUG, handlers=[console],
                        format="%(asctime)s %(levelname)s op=%(operation_id)s %(message)s")
    logging.info("Editor fixture uses the four Ctrl+Win+Z chords and the exact sample %r. Network is disabled.", SAMPLE)
    with patch.object(hotkey, "GrammarEngine", FixtureEngine):
        return hotkey.Listener(load_settings(SETTINGS_PATH), "").run()


if __name__ == "__main__":
    raise SystemExit(main())

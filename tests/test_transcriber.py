"""Проверка настоящего распознавания на тестовой записи (занимает ~10–60 секунд)."""

import os
import threading
import unittest

from app.transcriber import Transcriber, TranscriptionCancelled

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "samples", "sample_en.wav")


@unittest.skipUnless(os.path.isfile(SAMPLE), "нет samples/sample_en.wav")
class TranscriberTest(unittest.TestCase):
    transcriber = Transcriber()

    def test_recognizes_sample(self):
        progress = []
        segments, lang, duration = self.transcriber.transcribe(
            SAMPLE, "base", "auto", on_progress=lambda f, s: progress.append(f))
        text = " ".join(s.text for s in segments).lower()
        self.assertEqual(lang, "en")
        self.assertIn("test recording", text)
        self.assertIn("first release", text)
        self.assertTrue(all(s.end >= s.start for s in segments))
        self.assertTrue(progress and progress[-1] > 0.8)

    def test_cancel(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(TranscriptionCancelled):
            self.transcriber.transcribe(SAMPLE, "base", "en", cancel_event=cancel)

    def test_unknown_model(self):
        with self.assertRaises(ValueError):
            self.transcriber.transcribe(SAMPLE, "huge", "en")


if __name__ == "__main__":
    unittest.main()

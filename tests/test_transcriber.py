"""Проверка настоящего распознавания на тестовой записи (занимает ~10–60 секунд)."""

import os
import tempfile
import threading
import unittest
import wave

from app.transcriber import Transcriber, TranscriptionCancelled, language_name

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

    def test_silence_gives_no_text(self):
        """Отбраковка «неуверенных» фрагментов отключена (D-07) — в тишине модель не должна выдумывать текст."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "silence.wav")
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(b"\x00\x00" * 16000 * 10)
            segments, _lang, _duration = self.transcriber.transcribe(path, "base", "auto")
        self.assertEqual(segments, [])


class LanguageNameTest(unittest.TestCase):
    def test_known(self):
        self.assertEqual(language_name("ru"), "Русский")
        self.assertEqual(language_name("el"), "Греческий")  # раньше показывалось просто «el» (D-06)

    def test_unknown(self):
        self.assertEqual(language_name("xx"), "xx")
        self.assertEqual(language_name(None), "не определён")


if __name__ == "__main__":
    unittest.main()

"""Проверка настоящего распознавания на тестовой записи (занимает ~10–60 секунд)."""

import os
import tempfile
import threading
import unittest
import wave

from app.transcriber import (Transcriber, TranscriptionCancelled, clip_to_duration, language_name,
                             plan_language_runs)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "samples", "sample_en.wav")
# Живое чтение: 13 с английского вступления LibriVox, потом Л. Н. Толстой, «Детство», гл. XIX (2:10)
SAMPLE_RU = os.path.join(ROOT, "samples", "sample_ru.mp3")


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

    def test_english_sample_single_language(self):
        """Запись на одном языке не делится на участки."""
        self.transcriber.transcribe(SAMPLE, "base", "auto")
        self.assertEqual(self.transcriber.languages, ["en"])


@unittest.skipUnless(os.path.isfile(SAMPLE_RU), "нет samples/sample_ru.mp3")
class RussianMp3Test(unittest.TestCase):
    """Настоящая запись в MP3: английское вступление и русская речь."""
    transcriber = Transcriber()

    def check(self, model):
        segments, lang, duration = self.transcriber.transcribe(SAMPLE_RU, model, "auto")
        intro = " ".join(s.text for s in segments if s.end <= 14.5).lower()
        text = " ".join(s.text for s in segments if s.start >= 14).lower()
        self.assertEqual(lang, "ru")
        self.assertEqual(self.transcriber.languages, ["ru", "en"])
        self.assertIn("librivox", intro)            # D-09: вступление по-английски, а не «либри вакс»
        self.assertIn("public domain", intro)
        self.assertIn("москв", text)
        self.assertGreater(segments[-1].end, duration - 5)       # текст есть до конца записи
        for prev, cur in zip(segments, segments[1:]):
            self.assertLessEqual(prev.end, cur.start + 0.01)      # фрагменты не наезжают друг на друга
        for s in segments:
            self.assertLessEqual(s.start, s.end)
            self.assertLessEqual(s.end, duration)                 # D-08

    def test_base(self):
        self.check("base")

    def test_tiny(self):
        # на tiny проявлялся D-08: конец последнего фрагмента 130,6 с при длине записи 129,8 с
        self.check("tiny")

    def test_forced_language_not_split(self):
        """Если язык выбран вручную, запись не делится по языкам."""
        segments, lang, _duration = self.transcriber.transcribe(SAMPLE_RU, "tiny", "ru")
        self.assertEqual(lang, "ru")
        self.assertEqual(self.transcriber.languages, ["ru"])
        self.assertTrue(segments)


class ClipToDurationTest(unittest.TestCase):
    def test_end_after_file_end(self):
        self.assertEqual(clip_to_duration(127.0, 130.6, 129.8), (127.0, 129.8))   # D-08

    def test_start_after_file_end(self):
        self.assertEqual(clip_to_duration(130.0, 131.0, 129.8), (129.8, 129.8))

    def test_inside_unchanged(self):
        self.assertEqual(clip_to_duration(1.0, 2.5, 129.8), (1.0, 2.5))

    def test_unknown_duration(self):
        self.assertEqual(clip_to_duration(1.0, 2.5, 0), (1.0, 2.5))


class PlanLanguageRunsTest(unittest.TestCase):
    """Правило деления записи на участки с одним языком (D-09)."""

    def test_single_language(self):
        detected = [(0.4, 14.0, "ru", 0.9), (14.7, 19.4, "ru", 0.95)]
        self.assertEqual(plan_language_runs(detected, "ru", 20.0), [(0.0, 20.0, "ru")])

    def test_english_intro(self):
        detected = [(0.5, 14.0, "en", 0.92), (15.0, 19.5, "ru", 0.95), (20.0, 25.5, "ru", 0.98)]
        self.assertEqual(plan_language_runs(detected, "ru", 30.0),
                         [(0.0, 14.5, "en"), (14.5, 30.0, "ru")])   # граница — посередине паузы

    def test_unsure_other_language_ignored(self):
        detected = [(0.0, 5.0, "ru", 0.9), (5.5, 9.0, "uk", 0.5), (9.5, 15.0, "ru", 0.9)]
        self.assertEqual(plan_language_runs(detected, "ru", 15.0), [(0.0, 15.0, "ru")])

    def test_short_other_language_ignored(self):
        detected = [(0.0, 5.0, "ru", 0.9), (5.5, 6.5, "en", 0.99), (7.0, 15.0, "ru", 0.9)]
        self.assertEqual(plan_language_runs(detected, "ru", 15.0), [(0.0, 15.0, "ru")])

    def test_language_in_middle(self):
        detected = [(0.0, 5.0, "ru", 0.9), (6.0, 12.0, "en", 0.95), (13.0, 20.0, "ru", 0.9)]
        self.assertEqual(plan_language_runs(detected, "ru", 21.0),
                         [(0.0, 5.5, "ru"), (5.5, 12.5, "en"), (12.5, 21.0, "ru")])

    def test_no_speech(self):
        self.assertEqual(plan_language_runs([], "ru", 10.0), [(0.0, 10.0, "ru")])


class LanguageNameTest(unittest.TestCase):
    def test_known(self):
        self.assertEqual(language_name("ru"), "Русский")
        self.assertEqual(language_name("el"), "Греческий")  # раньше показывалось просто «el» (D-06)

    def test_unknown(self):
        self.assertEqual(language_name("xx"), "xx")
        self.assertEqual(language_name(None), "не определён")


if __name__ == "__main__":
    unittest.main()

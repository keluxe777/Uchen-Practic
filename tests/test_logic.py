"""Автотесты логики (без окна). Запуск: python -m unittest -v"""

import json
import os
import shutil
import tempfile
import unittest
import wave

from app.audio_utils import AudioFileError, check_audio_file, get_audio_info
from app.exporter import ExportError, export_docx, export_srt, export_txt, load_project, save_project, segments_to_srt
from app.history import History
from app.models import Project, Segment, format_time
from app.text_tools import find_segments, get_stats, replace_in_segments

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "samples", "sample_en.wav")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def make_segments():
    return [Segment(0.0, 2.5, "Привет, это тест."), Segment(3.0, 75.5, "Пиксель и код делает релиз.")]


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.tmp, name)


class FormatTimeTest(unittest.TestCase):
    def test_short(self):
        self.assertEqual(format_time(75.5), "01:15")

    def test_hours(self):
        self.assertEqual(format_time(3675), "1:01:15")

    def test_srt(self):
        self.assertEqual(format_time(75.5, srt=True), "00:01:15,500")

    def test_negative_is_zero(self):
        self.assertEqual(format_time(-3), "00:00")


class AudioCheckTest(TempDirTest):
    def test_missing_file(self):
        with self.assertRaises(AudioFileError):
            check_audio_file(self.path("нет.wav"))

    def test_empty_path(self):
        with self.assertRaises(AudioFileError):
            check_audio_file("")

    def test_wrong_extension(self):
        p = self.path("doc.txt")
        with open(p, "w") as f:
            f.write("text")
        with self.assertRaisesRegex(AudioFileError, "не поддерживается"):
            check_audio_file(p)

    def test_empty_file(self):
        p = self.path("empty.wav")
        open(p, "wb").close()
        with self.assertRaisesRegex(AudioFileError, "пустой"):
            check_audio_file(p)

    def test_broken_file(self):
        p = self.path("broken.mp3")
        with open(p, "wb") as f:
            f.write(b"this is not audio" * 100)
        with self.assertRaises(AudioFileError):
            get_audio_info(p)

    def test_silent_short_wav(self):
        p = self.path("short.wav")
        with wave.open(p, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 800)  # 0.05 секунды
        with self.assertRaisesRegex(AudioFileError, "короткая"):
            get_audio_info(p)

    @unittest.skipUnless(os.path.isfile(SAMPLE), "нет samples/sample_en.wav")
    def test_sample_info(self):
        info = get_audio_info(SAMPLE)
        self.assertAlmostEqual(info["duration"], 16.4, delta=0.5)
        self.assertEqual(info["format"], "WAV")


class TextToolsTest(unittest.TestCase):
    def test_find_ignore_case(self):
        self.assertEqual(find_segments(make_segments(), "пиксель"), [1])

    def test_find_match_case(self):
        self.assertEqual(find_segments(make_segments(), "пиксель", match_case=True), [])

    def test_find_empty_query(self):
        self.assertEqual(find_segments(make_segments(), ""), [])

    def test_replace(self):
        segs = make_segments()
        self.assertEqual(replace_in_segments(segs, "КОД", "Code"), 1)
        self.assertEqual(segs[1].text, "Пиксель и Code делает релиз.")

    def test_replace_special_chars(self):
        segs = make_segments()
        replace_in_segments(segs, "тест.", r"\1 (а+б)")
        self.assertEqual(segs[0].text, r"Привет, это \1 (а+б)")

    def test_stats(self):
        st = get_stats(make_segments(), 80)
        self.assertEqual(st["segments"], 2)
        self.assertEqual(st["words"], 8)
        self.assertGreater(st["words_per_minute"], 0)

    def test_stats_empty(self):
        self.assertEqual(get_stats([], 0)["words_per_minute"], 0)


class ExportTest(TempDirTest):
    def test_txt_with_timecodes(self):
        p = self.path("a.txt")
        export_txt(make_segments(), p, with_timecodes=True)
        text = read(p)
        self.assertIn("[00:00 – 00:02] Привет, это тест.", text)

    def test_txt_without_timecodes(self):
        p = self.path("a.txt")
        export_txt(make_segments(), p, with_timecodes=False)
        self.assertEqual(read(p).strip(),
                         "Привет, это тест. Пиксель и код делает релиз.")

    def test_srt(self):
        srt = segments_to_srt(make_segments())
        self.assertTrue(srt.startswith("1\n00:00:00,000 --> 00:00:02,500\nПривет, это тест.\n"))
        self.assertIn("2\n00:00:03,000 --> 00:01:15,500\n", srt)

    def test_srt_file(self):
        p = self.path("a.srt")
        export_srt(make_segments(), p)
        self.assertTrue(os.path.getsize(p) > 0)

    def test_docx(self):
        from docx import Document
        p = self.path("a.docx")
        export_docx(make_segments(), p, source_name="test.wav")
        text = "\n".join(par.text for par in Document(p).paragraphs)
        self.assertIn("Пиксель и код делает релиз.", text)
        self.assertIn("test.wav", text)

    def test_export_empty(self):
        with self.assertRaises(ExportError):
            export_txt([], self.path("a.txt"))

    def test_export_bad_folder(self):
        with self.assertRaises(ExportError):
            export_txt(make_segments(), self.path("нет_папки/a.txt"))


class ProjectTest(TempDirTest):
    def test_save_and_load(self):
        p = self.path("p.json")
        project = Project("C:/a.wav", 80, "ru", "base", make_segments())
        save_project(project, p)
        loaded = load_project(p)
        self.assertEqual(loaded.segments, project.segments)
        self.assertEqual(loaded.model, "base")

    def test_load_broken_json(self):
        p = self.path("p.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write("{ не json")
        with self.assertRaisesRegex(ExportError, "повреждён"):
            load_project(p)

    def test_load_foreign_json(self):
        p = self.path("p.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"name": "что-то другое"}, f)
        with self.assertRaises(ExportError):
            load_project(p)

    def test_load_bad_segment_time(self):
        p = self.path("p.json")
        data = Project("a.wav", 10, "ru", "base", make_segments()).to_dict()
        data["segments"][0]["end"] = -5
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f)
        with self.assertRaises(ExportError):
            load_project(p)

    def test_load_missing(self):
        with self.assertRaises(ExportError):
            load_project(self.path("нет.json"))


class HistoryTest(TempDirTest):
    def test_add_and_reload(self):
        p = self.path("h.json")
        h = History(p)
        h.add("a.wav", 10, 5, "base")
        h.add("b.wav", 20, 7, "tiny")
        h.add("a.wav", 10, 6, "base")  # повтор — поднимается наверх, без дубля
        again = History(p)
        self.assertEqual([x["audio_path"] for x in again.items], ["a.wav", "b.wav"])
        self.assertEqual(again.items[0]["words"], 6)

    def test_broken_history_file(self):
        p = self.path("h.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write("мусор")
        self.assertEqual(History(p).items, [])

    def test_limit(self):
        h = History(self.path("h.json"))
        for i in range(40):
            h.add(f"{i}.wav", 1, 1, "base")
        self.assertEqual(len(h.items), 30)


if __name__ == "__main__":
    unittest.main()

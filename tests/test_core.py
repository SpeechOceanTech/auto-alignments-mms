import csv
from pathlib import Path
import tempfile
import unittest
import wave
from unittest.mock import patch

from alignment_core import (align, read_sentences, romanize, write_outputs, _times_from_path,
                            _emission_frame_count, _required_ctc_frames, _precheck_ctc)
from alignment_vad import refine_times


class CoreTests(unittest.TestCase):
    def test_input_supports_plain_and_id_lines(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'sentences.txt'
            path.write_text('\ufeff第一句\n\ncustom-id\tSentence, two.\n', encoding='utf-8')
            self.assertEqual(read_sentences(path), [('1', '第一句'), ('custom-id', 'Sentence, two.')])
            path.write_text('id\t\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                read_sentences(path)

    def test_romanization_handles_multiple_scripts_and_empty_line(self):
        tokens = romanize([('a', 'Hello!'), ('b', '你好')], 'cmn')
        self.assertEqual(tokens, [list('hello'), list('nihao')])
        with self.assertRaisesRegex(ValueError, 'no alignable characters'):
            romanize([('a', '。')], 'cmn')

    def test_arabic_varieties_use_legacy_arabic_romanization(self):
        sentences = [('1', 'ٱلسَّلَامُ عَلَيْكُمْ'), ('2', 'كيف حالك اليوم؟')]
        expected = romanize(sentences, 'ara')
        for iso in ('arb', 'arz', 'ary', 'arq', 'acm', 'afb', 'ajp'):
            with self.subTest(iso=iso):
                self.assertEqual(romanize(sentences, iso), expected)

    def test_bracket_annotations_are_excluded_only_from_alignment(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            audio = root / 'audio.wav'
            audio.write_bytes(b'fixture')
            original = '你好【笑声】世界！【背景音乐】再见。'
            (root / 'input.txt').write_text(f'line-1\t{original}\n', encoding='utf-8')
            with patch('alignment_core._precheck_ctc'), patch('alignment_core._alignment', return_value=([(0.1, 1.0)], 1.2)) as alignment, patch('alignment_core.speech_timestamps', return_value=[(0.1, 1.0)]):
                paths = align(audio, root / 'input.txt', 'zh_cn', root / 'output', already_converted=True)
            self.assertEqual(alignment.call_args.args[1], [list('nihaoshijiezaijian')])
            with paths['csv'].open(encoding='utf-8-sig', newline='') as f:
                self.assertEqual(list(csv.reader(f, delimiter='\t'))[1][5], original)
            self.assertIn(original, paths['txt'].read_text(encoding='utf-8'))
            self.assertIn(f'text = "{original}"', paths['textgrid'].read_text(encoding='utf-8'))

    def test_bracket_only_sentence_rejected_with_correct_index(self):
        with self.assertRaisesRegex(ValueError, 'Sentence 2 has no alignable characters'):
            romanize([('1', 'Hello!'), ('2', '【笑声】！？')], 'eng')

    def test_other_bracket_types_keep_their_text_for_alignment(self):
        self.assertEqual(romanize([('1', 'Hello (world), [again] 【ignored】!')], 'eng'),
                         [list('helloworldagain')])

    def test_formats_preserve_text_and_gaps(self):
        with tempfile.TemporaryDirectory() as d:
            paths = write_outputs([('1', 'hello, "world"'), ('2', '你好')], [(0.5, 1.5), (2, 3)], 4, d)
            with paths['csv'].open(encoding='utf-8', newline='') as f:
                rows = list(csv.reader(f, delimiter='\t'))
            self.assertEqual(rows[0], ['Name', 'Start', 'Duration', 'Time Format', 'Type', 'Description'])
            self.assertEqual(rows[1], ['1', '00:00:00.500000', '00:00:01.000000', 'decimal', 'Cue', 'hello, "world"'])
            grid = paths['textgrid'].read_text(encoding='utf-8')
            self.assertIn('text = "hello, ""world"""', grid)
            self.assertIn('intervals: size = 5', grid)
            with self.assertRaises(ValueError):
                write_outputs([('a', 'a'), ('b', 'b')], [(0, 2), (1, 3)], 4, d)

    def test_main_flow_and_locale(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'audio.wav').write_bytes(b'audio')
            (root / 'input.txt').write_text('hello', encoding='utf-8')
            # Exercise orchestration without requiring the large model or ffmpeg.
            with patch('alignment_core.convert_audio') as convert, patch('alignment_core._precheck_ctc'), patch('alignment_core.romanize', return_value=[list('hello')]) as roman, patch('alignment_core._alignment', return_value=([(0.1, 1.0)], 1.2)), patch('alignment_core.speech_timestamps', return_value=[(0.1, 1.0)]):
                result = align(root / 'audio.wav', root / 'input.txt', 'en_us', root / 'output')
            self.assertEqual(roman.call_args.args[1], 'eng')
            self.assertEqual(set(result), {'csv', 'txt', 'textgrid'})
            self.assertTrue(all(path.is_file() for path in result.values()))
            self.assertEqual(convert.call_args.args[0], root / 'audio.wav')

    def test_ctc_blank_padding_matches_original_inclusive_frames(self):
        # star, blank, two transcript letters, blank, star
        path = [9, 9, 0, 0, 0, 1, 1, 0, 2, 2, 0, 0, 0, 0, 9]
        times = _times_from_path(path, [9, 1, 2, 9], [(1, 3)], 0, 0.02)
        self.assertEqual(times, [(0.06, 0.22)])

    def test_preconverted_audio_is_reused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            audio = root / 'normalized.wav'
            audio.write_bytes(b'fixture')
            (root / 'input.txt').write_text('hello')
            with patch('alignment_core.convert_audio') as convert, patch('alignment_core._precheck_ctc'), patch('alignment_core.romanize', return_value=[list('hello')]), patch('alignment_core._alignment', return_value=([(0.1, 1.0)], 1.2)) as alignment, patch('alignment_core.speech_timestamps', return_value=[(0.1, 1.0)]) as vad:
                align(audio, root / 'input.txt', 'en_us', root / 'output', already_converted=True)
            convert.assert_not_called()
            self.assertEqual(alignment.call_args.args[0], audio)
            self.assertEqual(vad.call_args.args[0], audio)

    def test_ctc_frame_count_at_chunk_boundaries(self):
        for samples, expected in ((399, 0), (400, 1), (719, 1), (720, 2),
                                  (480000, 1499), (480320, 1500),
                                  (528000, 1649), (960000, 2999)):
            with self.subTest(samples=samples):
                self.assertEqual(_emission_frame_count(samples), expected)

    def test_ctc_required_frames_include_stars_and_repeated_letters(self):
        self.assertEqual(_required_ctc_frames([list('a')]), 3)
        self.assertEqual(_required_ctc_frames([list('aa')]), 5)
        # Stars separate the same letter across sentences; no blank is needed.
        self.assertEqual(_required_ctc_frames([list('a'), list('a')]), 5)

    def test_ctc_precheck_allows_exact_fit_and_rejects_impossible_input(self):
        with tempfile.TemporaryDirectory() as d:
            audio = Path(d) / 'normalized.wav'
            with wave.open(str(audio), 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(b'\0\0' * 1680)  # exactly 5 model frames
            _precheck_ctc(audio, [list('aa')])
            with self.assertRaisesRegex(ValueError, 'requires 7 CTC frames, audio provides 5'):
                _precheck_ctc(audio, [list('aaa')])

    def test_ctc_precheck_runs_before_vad_and_model(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            audio = root / 'normalized.wav'
            with wave.open(str(audio), 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(b'\0\0' * 1040)  # 3 frames
            (root / 'input.txt').write_text('aaaa', encoding='utf-8')
            with patch('alignment_core.speech_timestamps') as vad, patch('alignment_core._alignment') as alignment:
                with self.assertRaisesRegex(ValueError, 'Transcript is too long'):
                    align(audio, root / 'input.txt', 'en_us', root / 'out', already_converted=True)
            vad.assert_not_called()
            alignment.assert_not_called()

    def test_silence_refinement_and_overlap(self):
        self.assertEqual(refine_times([(0.9, 2.1), (2.0, 3.9)], [(1., 2.), (2.4, 4.)], 5.), [(0.5, 2.2), (2.2, 4.5)])
        # If the nearest silences would overlap, original code splits them.
        self.assertEqual(refine_times([(0.9, 2.1), (2.0, 2.2)], [(1., 2.), (3., 4.)], 5.), [(0.5, 2.25), (2.25, 4.5)])


if __name__ == '__main__':
    unittest.main()

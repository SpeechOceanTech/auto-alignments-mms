from pathlib import Path
import tempfile
import unittest

from alignment_web.error_messages import explain_error


class ErrorMessageTests(unittest.TestCase):
    def test_historical_traceback_reports_actual_line_and_id(self):
        traceback = '''Traceback (most recent call last):
  File "alignment_core.py", line 81, in romanize
    raise ValueError(f"Sentence {i + 1} has no alignable characters after normalization")
ValueError: Sentence 2 has no alignable characters after normalization'''
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'input.txt'
            path.write_text('\ufeff第一句\n\n04_003166_0001_B\t-\n', encoding='utf-8')
            result = explain_error(traceback, path)
        self.assertEqual(result['code'], 'empty_sentence')
        for expected in ('第 2 句', '第 3 行', '04_003166_0001_B', '原文：-', '实际朗读'):
            self.assertIn(expected, result['message'])

    def test_missing_or_invalid_input_still_has_sentence_number(self):
        error = 'ValueError: Sentence 157 has no alignable characters after normalization'
        result = explain_error(error, '/no/such/file')
        self.assertEqual(result['code'], 'empty_sentence')
        self.assertIn('第 157 句', result['message'])

    def test_plain_text_id_and_previews_are_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'input.txt'
            path.write_text('x' * 300 + '\n', encoding='utf-8')
            message = explain_error('ValueError: Sentence 1 has no alignable characters after normalization', path)['message']
        self.assertIn('ID：1', message)
        self.assertIn('…', message)
        self.assertNotIn('x' * 300, message)

    def test_classifies_only_the_final_exception(self):
        error = ('Traceback (most recent call last):\n'
                 'ValueError: Sentence 5 has no alignable characters after normalization\n\n'
                 'During handling of the above exception, another exception occurred:\n\n'
                 'Traceback (most recent call last):\nRuntimeError: unrelated')
        self.assertEqual(explain_error(error), {'code': 'unknown', 'message': error})
        source = '  raise ValueError("Sentence 3 has no alignable characters after normalization")\nRuntimeError: unrelated'
        self.assertEqual(explain_error(source)['code'], 'unknown')

    def test_too_long_and_unknown_errors(self):
        error = 'Traceback (most recent call last):\nValueError: Transcript is too long for the supplied audio: 123 tokens'
        result = explain_error(error)
        self.assertEqual(result['code'], 'transcript_too_long')
        self.assertIn('文本相对于音频过长', result['message'])
        self.assertEqual(explain_error('backend failure'), {'code': 'unknown', 'message': 'backend failure'})
        self.assertEqual(explain_error('   '), {'code': 'unknown', 'message': '   '})
        self.assertIsNone(explain_error(None))


if __name__ == '__main__':
    unittest.main()

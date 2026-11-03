import csv
import tempfile
import unittest
from pathlib import Path

from alignment_csv import audition_csv_bytes, read_alignment_csv, write_audition_csv


class AlignmentCsvTests(unittest.TestCase):
    def test_original_audition_format_and_round_trip(self):
        rows = [
            {'id': '片段,1', 'start': 1.234, 'end': 2.345, 'text': '你好，"world"\t再见\n第二行'},
            {'id': 'long', 'start': 90061.125, 'end': 90062.5, 'text': 'plain'},
        ]
        encoded = audition_csv_bytes(rows)
        self.assertFalse(encoded.startswith(b'\xef\xbb\xbf'))
        self.assertTrue(encoded.startswith(b'Name\tStart\tDuration\tTime Format\tType\tDescription\n'))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'result.csv'
            write_audition_csv(path, rows)
            self.assertEqual(path.read_bytes(), encoded)
            with path.open(encoding='utf-8', newline='') as file:
                values = list(csv.reader(file, delimiter='\t'))
            self.assertEqual(values[1][1:5], ['00:00:01.234000', '00:00:01.111000', 'decimal', 'Cue'])
            self.assertEqual(values[2][1:3], ['25:01:01.125000', '00:00:01.375000'])
            self.assertEqual(read_alignment_csv(path), rows)

    def test_old_csv_and_original_audition_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'result.csv'
            path.write_text('\ufeffid,start,end,text\nhello,1.234,2.345,"你好, 世界"\n', encoding='utf-8')
            expected = [{'id': 'hello', 'start': 1.234, 'end': 2.345, 'text': '你好, 世界'}]
            self.assertEqual(read_alignment_csv(path), expected)
            path.write_bytes(audition_csv_bytes(expected))
            self.assertEqual(read_alignment_csv(path), expected)

    def test_existing_audition_microsecond_precision_survives_download(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'result.csv'
            path.write_text('Name\tStart\tDuration\tTime Format\tType\tDescription\n'
                            'one\t00:00:00.123456\t00:00:00.333333\tdecimal\tCue\t中文\n', encoding='utf-8')
            expected = read_alignment_csv(path)
            self.assertEqual(expected[0]['end'], 0.456789)
            path.write_bytes(audition_csv_bytes(expected))
            self.assertIn('00:00:00.123456\t00:00:00.333333', path.read_text(encoding='utf-8'))
            self.assertEqual(read_alignment_csv(path), expected)

    def test_invalid_timing_and_schema_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.csv'
            for content in [
                'wrong,header\n1,2\n',
                'id,start,end,text\n1,nan,1,test\n',
                'id,start,end,text\n1,2,1,test\n',
                'Name\tStart\tDuration\tTime Format\tType\tDescription\n1\t00:60:00.0\t00:00:01.0\tdecimal\tCue\tx\n',
            ]:
                path.write_text(content, encoding='utf-8')
                with self.subTest(content=content), self.assertRaises(ValueError):
                    read_alignment_csv(path)


if __name__ == '__main__':
    unittest.main()

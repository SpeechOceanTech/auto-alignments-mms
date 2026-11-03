"""Read alignment results and write Adobe Audition marker lists.

Audition uses a tab-separated marker list despite the .csv extension. Older
versions of this service wrote a comma-separated id/start/end/text file.
"""
import csv
from decimal import Decimal, InvalidOperation
import io
from pathlib import Path


AUDITION_HEADER = ('Name', 'Start', 'Duration', 'Time Format', 'Type', 'Description')
LEGACY_HEADER = ('id', 'start', 'end', 'text')


def _seconds(value):
    """Parse decimal seconds or an unbounded HH:MM:SS.fraction timestamp."""
    try:
        value = str(value).strip()
        if ':' in value:
            parts = value.split(':')
            if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
                raise ValueError('Invalid timestamp')
            hours, minutes = int(parts[0]), int(parts[1])
            seconds = Decimal(parts[2])
            if minutes >= 60 or not seconds.is_finite() or not 0 <= seconds < 60:
                raise ValueError('Invalid timestamp')
            result = Decimal(hours * 3600 + minutes * 60) + seconds
        else:
            result = Decimal(value)
        if not result.is_finite() or result < 0:
            raise ValueError('Invalid timestamp')
        return result
    except (InvalidOperation, TypeError, OverflowError) as exc:
        raise ValueError('Invalid timestamp') from exc


def _timestamp(seconds):
    microseconds = int((seconds * 1_000_000).to_integral_value())
    hours, rest = divmod(microseconds, 3_600_000_000)
    minutes, rest = divmod(rest, 60_000_000)
    whole_seconds, fraction = divmod(rest, 1_000_000)
    return f'{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{fraction:06d}'


def read_alignment_csv(path):
    """Return normalized id/start/end/text rows from either supported format.

    Timing values are seconds as floats. Unsupported or malformed files raise
    ValueError; I/O and Unicode failures are left to the caller.
    """
    try:
        with Path(path).open(encoding='utf-8-sig', newline='') as source:
            first = source.readline()
            source.seek(0)
            delimiter = '\t' if first.rstrip('\r\n').split('\t') == list(AUDITION_HEADER) else ','
            reader = csv.DictReader(source, delimiter=delimiter, strict=True)
            if tuple(reader.fieldnames or ()) == AUDITION_HEADER:
                audition = True
            elif tuple(reader.fieldnames or ()) == LEGACY_HEADER:
                audition = False
            else:
                raise ValueError('Unsupported alignment CSV header')
            result = []
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError('Malformed alignment CSV row')
                if audition:
                    if row['Time Format'] != 'decimal' or row['Type'] != 'Cue':
                        raise ValueError('Unsupported Audition marker')
                    start = _seconds(row['Start'])
                    end = start + _seconds(row['Duration'])
                    name, text = row['Name'], row['Description']
                else:
                    start, end = _seconds(row['start']), _seconds(row['end'])
                    name, text = row['id'], row['text']
                if end < start:
                    raise ValueError('Invalid alignment interval')
                result.append({'id': name, 'start': float(start), 'end': float(end), 'text': text})
            return result
    except csv.Error as exc:
        raise ValueError('Malformed alignment CSV') from exc


def audition_csv_bytes(rows):
    """Serialize normalized rows as a UTF-8 Audition marker list."""
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer, delimiter='\t', lineterminator='\n')
    writer.writerow(AUDITION_HEADER)
    for row in rows:
        start = _seconds(row['start'])
        end = _seconds(row['end'])
        if end < start:
            raise ValueError('Invalid alignment interval')
        # Normalize both boundaries to microseconds before subtracting, so a
        # round-trip preserves existing Audition marker precision.
        start = start.quantize(Decimal('0.000001'))
        end = end.quantize(Decimal('0.000001'))
        writer.writerow([row['id'], _timestamp(start), _timestamp(end - start),
                         'decimal', 'Cue', row['text']])
    return buffer.getvalue().encode('utf-8')


def write_audition_csv(path, rows):
    Path(path).write_bytes(audition_csv_bytes(rows))

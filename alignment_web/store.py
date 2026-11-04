"""Persistent task queue. Each operation uses its own SQLite connection."""
import sqlite3
from pathlib import Path


class JobStore:
    def __init__(self, path: Path):
        self.path = path
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, language TEXT NOT NULL, audio_name TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, error TEXT, owner_id TEXT
            )""")
            if 'owner_id' not in {row['name'] for row in db.execute('PRAGMA table_info(jobs)')}:
                db.execute('ALTER TABLE jobs ADD COLUMN owner_id TEXT')
            db.execute("""CREATE TABLE IF NOT EXISTS completion_facts (
                job_id TEXT PRIMARY KEY, language TEXT NOT NULL, owner_id TEXT,
                completed_at TEXT NOT NULL, audio_seconds REAL, sentence_count INTEGER
            )""")
            if 'batch_id' not in {row['name'] for row in db.execute('PRAGMA table_info(jobs)')}:
                db.execute('ALTER TABLE jobs ADD COLUMN batch_id TEXT')
            db.execute('CREATE INDEX IF NOT EXISTS jobs_owner_id ON jobs(owner_id)')
            db.execute('CREATE INDEX IF NOT EXISTS jobs_batch_id ON jobs(batch_id)')
            db.execute('''CREATE TABLE IF NOT EXISTS batches (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, language TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE IF NOT EXISTS batch_items (
                batch_id TEXT NOT NULL, audio_name TEXT NOT NULL, text_name TEXT NOT NULL,
                job_id TEXT, PRIMARY KEY(batch_id, audio_name, text_name))''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def recover(self):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='failed', error=?, updated_at=CURRENT_TIMESTAMP WHERE status='running'",
                       ('服务重启，任务中断；请重新提交。',))

    def create(self, job_id, language, audio_name, owner_id=None, batch_id=None, batch_audio=None, batch_text=None):
        with self.connect() as db:
            if batch_id:
                db.execute('BEGIN IMMEDIATE')
                item = db.execute("SELECT job_id FROM batch_items WHERE batch_id=? AND audio_name=? AND text_name=?",
                                  (batch_id, batch_audio, batch_text)).fetchone()
                if item is None:
                    raise ValueError('文件不属于这个批次')
                if item['job_id']:
                    return item['job_id']
            db.execute("INSERT INTO jobs (id, language, audio_name, status, owner_id, batch_id) VALUES (?, ?, ?, 'queued', ?, ?)",
                       (job_id, language, audio_name, owner_id, batch_id))
            if batch_id:
                db.execute('UPDATE batch_items SET job_id=? WHERE batch_id=? AND audio_name=? AND text_name=?',
                           (job_id, batch_id, batch_audio, batch_text))
            return job_id

    def create_batch(self, batch_id, owner_id, language, pairs):
        with self.connect() as db:
            db.execute('INSERT INTO batches(id, owner_id, language) VALUES (?, ?, ?)', (batch_id, owner_id, language))
            db.executemany('INSERT INTO batch_items(batch_id, audio_name, text_name) VALUES (?, ?, ?)',
                           [(batch_id, pair['audio'], pair['text']) for pair in pairs])

    def get_batch(self, batch_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM batches WHERE id=?', (batch_id,)).fetchone()
            return dict(row) if row else None

    def get_batch_item(self, batch_id, audio_name, text_name):
        with self.connect() as db:
            row = db.execute('SELECT job_id FROM batch_items WHERE batch_id=? AND audio_name=? AND text_name=?',
                             (batch_id, audio_name, text_name)).fetchone()
            return dict(row) if row else None

    def list_batches(self, owner_id=None):
        with self.connect() as db:
            return [dict(row) for row in db.execute("""SELECT b.*,
                (SELECT count(*) FROM batch_items i WHERE i.batch_id=b.id) AS total,
                (SELECT count(*) FROM batch_items i WHERE i.batch_id=b.id AND i.job_id IS NULL) AS unsubmitted,
                (SELECT count(*) FROM jobs j WHERE j.batch_id=b.id AND j.status='queued') AS queued,
                (SELECT count(*) FROM jobs j WHERE j.batch_id=b.id AND j.status='running') AS running,
                (SELECT count(*) FROM jobs j WHERE j.batch_id=b.id AND j.status='completed') AS completed,
                (SELECT count(*) FROM jobs j WHERE j.batch_id=b.id AND j.status='failed') AS failed
                FROM batches b WHERE (? IS NULL OR b.owner_id=?) ORDER BY b.created_at DESC, b.rowid DESC""",
                (owner_id, owner_id))]

    def batch_jobs(self, batch_id):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM jobs WHERE batch_id=? ORDER BY rowid', (batch_id,))]

    def get(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            return dict(row) if row else None

    def list(self, limit, offset, status=None, language=None, q=None, created_from=None, created_to=None, owner_id=None, legacy_language=None, legacy_owner=False, batch_id=None):
        conditions, values = [], []
        if legacy_owner:
            conditions.append('owner_id IS NULL')
        elif owner_id is not None:
            conditions.append('owner_id=?')
            values.append(owner_id)
        if batch_id:
            conditions.append('batch_id=?')
            values.append(batch_id)
        if status:
            conditions.append('status=?')
            values.append(status)
        if language:
            languages = list(dict.fromkeys((language, legacy_language or language)))
            conditions.append('language IN (' + ','.join('?' for _ in languages) + ')')
            values.extend(languages)
        if q:
            conditions.append('(instr(lower(audio_name), lower(?)) > 0 OR instr(id, ?) > 0)')
            values.extend((q, q))
        if created_from:
            conditions.append('created_at >= ?')
            values.append(created_from + ' 00:00:00')
        if created_to:
            conditions.append('created_at < date(?, "+1 day")')
            values.append(created_to)
        where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
        with self.connect() as db:
            rows = db.execute('SELECT * FROM jobs' + where + ' ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?',
                              (*values, limit, offset)).fetchall()
            total = db.execute('SELECT count(*) FROM jobs' + where, values).fetchone()[0]
            return [dict(row) for row in rows], total

    def retry(self, job_id):
        with self.connect() as db:
            cur = db.execute("UPDATE jobs SET status='queued', error=NULL, updated_at=CURRENT_TIMESTAMP "
                             "WHERE id=? AND status='failed'", (job_id,))
            return cur.rowcount == 1

    def claim(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET status='running', updated_at=CURRENT_TIMESTAMP WHERE id=?", (row['id'],))
            return row['id']

    def finish(self, job_id, error=None, audio_seconds=None, sentence_count=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            cur = db.execute("UPDATE jobs SET status=?, error=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='running'",
                             ('failed' if error else 'completed', error, job_id))
            if cur.rowcount and not error:
                db.execute("""INSERT OR IGNORE INTO completion_facts
                    (job_id, language, owner_id, completed_at, audio_seconds, sentence_count)
                    SELECT id, language, owner_id, updated_at, ?, ? FROM jobs WHERE id=?""",
                    (audio_seconds, sentence_count, job_id))

    def seed_completed_statistics(self):
        # Preserve the historical count immediately; metadata is filled asynchronously.
        with self.connect() as db:
            db.execute("""INSERT OR IGNORE INTO completion_facts
                (job_id, language, owner_id, completed_at)
                SELECT id, language, owner_id, updated_at FROM jobs WHERE status='completed'""")

    def incomplete_statistics(self):
        with self.connect() as db:
            rows = db.execute("""SELECT j.id, j.audio_name FROM jobs j LEFT JOIN completion_facts f ON f.job_id=j.id
                WHERE j.status='completed' AND (f.job_id IS NULL OR f.audio_seconds IS NULL OR f.sentence_count IS NULL)""").fetchall()
            return [dict(row) for row in rows]

    def fill_statistics(self, job_id, audio_seconds, sentence_count):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("""INSERT OR IGNORE INTO completion_facts
                (job_id, language, owner_id, completed_at, audio_seconds, sentence_count)
                SELECT id, language, owner_id, updated_at, ?, ? FROM jobs WHERE id=? AND status='completed'""",
                (audio_seconds, sentence_count, job_id))
            db.execute("""UPDATE completion_facts SET audio_seconds=COALESCE(audio_seconds, ?),
                sentence_count=COALESCE(sentence_count, ?) WHERE job_id=?""",
                (audio_seconds, sentence_count, job_id))

    def usage(self):
        metrics = """count(*) AS jobs,
            coalesce(sum(f.audio_seconds), 0) AS audio_seconds,
            count(f.audio_seconds) AS audio_duration_sample_count,
            coalesce(sum(f.sentence_count), 0) AS sentence_count,
            count(f.sentence_count) AS sentence_sample_count"""
        # Old versions kept facts after deletion. Only count completed jobs
        # still present, including when an orphaned fact predates this change.
        source = " FROM completion_facts f JOIN jobs j ON j.id=f.job_id AND j.status='completed'"
        duration_order = ' ORDER BY (count(f.audio_seconds) = 0), sum(f.audio_seconds) DESC, '
        with self.connect() as db:
            db.execute('BEGIN')
            totals = dict(db.execute('SELECT ' + metrics + source).fetchone())
            languages = [dict(row) for row in db.execute('SELECT f.language, ' + metrics + source + ' GROUP BY f.language' + duration_order + 'f.language')]
            users = [dict(row) for row in db.execute('SELECT f.owner_id, ' + metrics + source + ' GROUP BY f.owner_id' + duration_order + 'f.owner_id')]
            statuses = dict(db.execute('SELECT status, count(*) FROM jobs GROUP BY status').fetchall())
        totals['completed'] = totals['jobs']
        return {'totals': totals, 'languages': languages, 'users': users,
                'current': {status: statuses.get(status, 0) for status in ('queued', 'running', 'completed', 'failed')}}

    def delete(self, job_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            cur = db.execute("DELETE FROM jobs WHERE id=? AND status IN ('completed', 'failed')", (job_id,))
            if cur.rowcount:
                db.execute('DELETE FROM completion_facts WHERE job_id=?', (job_id,))
                db.execute('UPDATE batch_items SET job_id=NULL WHERE job_id=?', (job_id,))
            return cur.rowcount == 1

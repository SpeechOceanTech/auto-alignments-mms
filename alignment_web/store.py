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
            db.execute('CREATE INDEX IF NOT EXISTS jobs_owner_id ON jobs(owner_id)')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def recover(self):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='failed', error=?, updated_at=CURRENT_TIMESTAMP WHERE status='running'",
                       ('服务重启，任务中断；请重新提交。',))

    def create(self, job_id, language, audio_name, owner_id=None):
        with self.connect() as db:
            db.execute("INSERT INTO jobs (id, language, audio_name, status, owner_id) VALUES (?, ?, ?, 'queued', ?)",
                       (job_id, language, audio_name, owner_id))

    def get(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            return dict(row) if row else None

    def list(self, limit, offset, status=None, language=None, q=None, created_from=None, created_to=None, owner_id=None, legacy_language=None):
        conditions, values = [], []
        if owner_id is not None:
            conditions.append('owner_id=?')
            values.append(owner_id)
        if status:
            conditions.append('status=?')
            values.append(status)
        if language:
            conditions.append('(language=? OR language=?)')
            values.extend((language, legacy_language or language))
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

    def finish(self, job_id, error=None):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status=?, error=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='running'",
                       ('failed' if error else 'completed', error, job_id))

    def delete(self, job_id):
        with self.connect() as db:
            cur = db.execute("DELETE FROM jobs WHERE id=? AND status IN ('completed', 'failed')", (job_id,))
            return cur.rowcount == 1

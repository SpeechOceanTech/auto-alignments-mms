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
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, error TEXT
            )""")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def recover(self):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='failed', error=?, updated_at=CURRENT_TIMESTAMP WHERE status='running'",
                       ('服务重启，任务中断；请重新提交。',))

    def create(self, job_id, language, audio_name):
        with self.connect() as db:
            db.execute("INSERT INTO jobs (id, language, audio_name, status) VALUES (?, ?, ?, 'queued')",
                       (job_id, language, audio_name))

    def get(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            return dict(row) if row else None

    def list(self, limit, offset):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?',
                              (limit, offset)).fetchall()
            total = db.execute('SELECT count(*) FROM jobs').fetchone()[0]
            return [dict(row) for row in rows], total

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

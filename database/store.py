"""SQLite storage. Each operation owns its connection, including worker threads."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / 'mangaflow.db'
STORAGE = ROOT / 'storage'


class Store:
    def __init__(self, path=DEFAULT_DB):
        self.path = Path(path).resolve()
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS invites (
                    code TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, login TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    invite TEXT UNIQUE REFERENCES invites(code) ON DELETE SET NULL,
                    hwid TEXT UNIQUE, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS hardware_requests (
                    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                    new_hwid TEXT NOT NULL, reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'reset_requested',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_pending_request
                    ON hardware_requests(user_id) WHERE status='reset_requested';
                CREATE TABLE IF NOT EXISTS batches (
                    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                    title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    output_dir TEXT, zip_path TEXT, error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS pages (
                    id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL, filename TEXT NOT NULL, source_path TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', result_path TEXT, error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS remote_accounts (
                    server_url TEXT NOT NULL, remote_user_id INTEGER NOT NULL,
                    local_user_id INTEGER NOT NULL REFERENCES users(id),
                    PRIMARY KEY(server_url,remote_user_id)
                );
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_batch(self, user_id, title, paths):
        with self.connect() as db:
            batch_id = db.execute('INSERT INTO batches(user_id,title) VALUES (?,?)',
                                  (user_id, title)).lastrowid
            db.executemany('INSERT INTO pages(batch_id,position,filename,source_path) VALUES (?,?,?,?)',
                           [(batch_id, i, Path(p).name, str(Path(p).resolve())) for i, p in enumerate(paths, 1)])
            return batch_id

    def link_remote_user(self, server_url, user):
        """History identity only: these rows never authorize the application."""
        import hashlib
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            linked = db.execute('SELECT local_user_id FROM remote_accounts WHERE server_url=? AND remote_user_id=?',
                                (server_url, user['id'])).fetchone()
            if linked:
                local_id = linked['local_user_id']
            else:
                legacy = db.execute('SELECT id FROM users WHERE login=? AND invite=?',
                                    (user['login'], user['invite'])).fetchone()
                if legacy:
                    local_id = legacy['id']
                else:
                    internal_login = 'remote_' + hashlib.sha256(f"{server_url}|{user['id']}".encode()).hexdigest()
                    local_id = db.execute('INSERT INTO users(login) VALUES (?)', (internal_login,)).lastrowid
                db.execute('INSERT INTO remote_accounts VALUES (?,?,?)', (server_url, user['id'], local_id))
        return {**user, 'remote_id': user['id'], 'id': local_id}

    def history(self, user_id):
        with self.connect() as db:
            return db.execute('''SELECT b.*, COUNT(p.id) AS page_count FROM batches b
                LEFT JOIN pages p ON p.batch_id=b.id WHERE b.user_id=?
                GROUP BY b.id ORDER BY b.id DESC''', (user_id,)).fetchall()

    def pages(self, batch_id):
        with self.connect() as db:
            return db.execute('SELECT * FROM pages WHERE batch_id=? ORDER BY position', (batch_id,)).fetchall()

    def statistics(self, user_id):
        with self.connect() as db:
            volumes = db.execute("SELECT COUNT(*) FROM batches WHERE user_id=? AND status='completed'", (user_id,)).fetchone()[0]
            pages = db.execute("""SELECT COUNT(*) FROM pages p JOIN batches b ON b.id=p.batch_id
                WHERE b.user_id=? AND p.status IN ('completed','partial')""", (user_id,)).fetchone()[0]
            return volumes, pages

    def update_batch(self, batch_id, status, output_dir=None, zip_path=None, error=None):
        with self.connect() as db:
            db.execute('UPDATE batches SET status=?,output_dir=?,zip_path=?,error=? WHERE id=?',
                       (status, str(output_dir) if output_dir else None,
                        str(zip_path) if zip_path else None, error, batch_id))

    def update_page(self, page_id, status, result_path=None, error=None):
        with self.connect() as db:
            db.execute('UPDATE pages SET status=?,result_path=?,error=? WHERE id=?',
                       (status, str(result_path) if result_path else None, error, page_id))

    def delete_batch(self, user_id, batch_id):
        # Results remain on disk; deleting history must not delete arbitrary paths.
        with self.connect() as db:
            db.execute('DELETE FROM batches WHERE id=? AND user_id=?', (batch_id, user_id))

    def recover_interrupted(self, user_id):
        """Call on startup only after taking the single-instance application lock."""
        with self.connect() as db:
            db.execute("""UPDATE pages SET status='failed',error='Приложение было прервано'
                WHERE status IN ('pending','processing') AND batch_id IN
                (SELECT id FROM batches WHERE user_id=? AND status IN ('pending','processing'))""", (user_id,))
            db.execute("""UPDATE batches SET status='failed',error='Приложение было прервано'
                WHERE user_id=? AND status IN ('pending','processing')""", (user_id,))

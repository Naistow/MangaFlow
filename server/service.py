import hashlib
import secrets
import time
from core.auth import AuthService, AuthError
from database.store import Store


class SessionDenied(AuthError):
    pass


class ServerAuth:
    def __init__(self, path, lifetime=7 * 86400):
        self.store = Store(path)
        self.local = AuthService(self.store)
        self.lifetime = lifetime
        with self.store.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS auth_sessions (
                token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                hwid TEXT NOT NULL, expires_at INTEGER NOT NULL)''')

    @staticmethod
    def token_hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def activate(self, login, code, hwid):
        user = self.local.activate(login, code, hwid)
        token = secrets.token_urlsafe(48)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT * FROM users WHERE id=? AND hwid=? AND invite IS NOT NULL',
                                 (user['id'], hwid)).fetchone()
            if not current:
                raise SessionDenied('Доступ изменён администратором. Повторите вход.')
            db.execute('DELETE FROM auth_sessions WHERE user_id=? OR expires_at<?', (user['id'], int(time.time())))
            db.execute('INSERT INTO auth_sessions VALUES (?,?,?,?)',
                       (self.token_hash(token), user['id'], hwid, int(time.time()) + self.lifetime))
        return {'user': dict(current), 'token': token}

    def validate(self, token, hwid):
        with self.store.connect() as db:
            user = db.execute('''SELECT u.* FROM auth_sessions s JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.hwid=? AND u.hwid=s.hwid
                AND u.invite IS NOT NULL AND s.expires_at>?''',
                (self.token_hash(token), hwid, int(time.time()))).fetchone()
            if user is None:
                raise SessionDenied('Сессия истекла или доступ отозван. Повторите вход.')
            return {'user': dict(user)}

    def request_reset(self, login, code, hwid, reason):
        self.local.request_reset(login, code, hwid, reason)
        return {'status': 'reset_requested'}

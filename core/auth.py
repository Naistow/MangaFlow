"""SQLite authority used by the administrator's server, with no model imports.

The desktop entry point uses core.remote_auth, never this local store for access.
"""
import hashlib
import re
import secrets
import string
import subprocess
import uuid

from database.store import Store


class AuthError(ValueError):
    pass


class HardwareMismatch(AuthError):
    pass


def get_hwid():
    """Hash MachineGuid and SMBIOS system UUID; never use an unstable fallback."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r'SOFTWARE\Microsoft\Cryptography', 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            machine_guid = str(winreg.QueryValueEx(key, 'MachineGuid')[0]).strip().lower()
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
             '(Get-CimInstance Win32_ComputerSystemProduct -ErrorAction Stop).UUID'],
            capture_output=True, text=True, timeout=20, check=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        board_uuid = str(uuid.UUID(result.stdout.strip()))
        if not machine_guid or uuid.UUID(board_uuid).int in (0, (1 << 128) - 1):
            raise ValueError('Invalid hardware identifiers')
        return hashlib.sha256(f'{machine_guid}|{board_uuid}'.encode()).hexdigest()
    except Exception as exc:
        raise AuthError('Не удалось прочитать MachineGuid/UUID компьютера. Проверьте доступ к реестру и CIM.') from exc


class AuthService:
    def __init__(self, store=None):
        self.store = store or Store()

    @staticmethod
    def _revoke_sessions(db, user_id):
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='auth_sessions'").fetchone():
            db.execute('DELETE FROM auth_sessions WHERE user_id=?', (user_id,))

    def generate_invites(self, count=1):
        if not 1 <= count <= 10000:
            raise AuthError('Количество кодов: от 1 до 10000.')
        codes = []
        with self.store.connect() as db:
            while len(codes) < count:
                chars = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
                code = f'MF-{chars[:4]}-{chars[4:]}'
                if db.execute('INSERT OR IGNORE INTO invites(code) VALUES (?)', (code,)).rowcount:
                    codes.append(code)
        return codes

    def automatic_login(self, hwid):
        with self.store.connect() as db:
            return db.execute('SELECT * FROM users WHERE hwid=? AND invite IS NOT NULL', (hwid,)).fetchone()

    def activate(self, login, code, hwid):
        login, code = login.strip(), code.strip().upper()
        if not re.fullmatch(r'[\w.-]{2,40}', login) or not re.fullmatch(r'MF-[A-Z0-9]{4}-[A-Z0-9]{4}', code):
            raise AuthError('Логин: 2–40 букв, цифр, точек, дефисов или _. Код: MF-XXXX-XXXX.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM invites WHERE code=?', (code,)).fetchone():
                raise AuthError('Инвайт не найден.')
            user = db.execute('SELECT * FROM users WHERE login=?', (login,)).fetchone()
            owner = db.execute('SELECT * FROM users WHERE invite=?', (code,)).fetchone()
            if owner and (not user or owner['id'] != user['id']):
                raise AuthError('Инвайт уже привязан к другому логину.')
            if user and user['invite'] != code:
                raise AuthError('Этот логин связан с другим инвайтом или доступ отозван.')
            if user and user['hwid'] and user['hwid'] != hwid:
                raise HardwareMismatch('Инвайт привязан к другому ПК. Подайте заявку на смену железа.')
            other = db.execute('SELECT id FROM users WHERE hwid=?', (hwid,)).fetchone()
            if other and (not user or other['id'] != user['id']):
                raise AuthError('Этот ПК уже привязан к другому пользователю.')
            if user:
                db.execute('UPDATE users SET hwid=? WHERE id=?', (hwid, user['id']))
            else:
                db.execute('INSERT INTO users(login,invite,hwid) VALUES (?,?,?)', (login, code, hwid))
            return db.execute('SELECT * FROM users WHERE login=?', (login,)).fetchone()

    def request_reset(self, login, code, hwid, reason):
        if not reason.strip() or len(reason.strip()) > 2000:
            raise AuthError('Укажите причину (1–2000 символов).')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            user = db.execute('SELECT * FROM users WHERE login=? AND invite=?',
                              (login.strip(), code.strip().upper())).fetchone()
            if not user or not user['hwid'] or user['hwid'] == hwid:
                raise AuthError('Заявка возможна только для своего инвайта с другого ПК.')
            existing = db.execute("SELECT id FROM hardware_requests WHERE user_id=? AND status='reset_requested'",
                                  (user['id'],)).fetchone()
            if existing:
                raise AuthError('Заявка уже ожидает решения администратора.')
            db.execute('INSERT INTO hardware_requests(user_id,new_hwid,reason) VALUES (?,?,?)',
                       (user['id'], hwid, reason.strip()))

    def review_reset(self, request_id, approve=True):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM hardware_requests WHERE id=? AND status='reset_requested'",
                             (request_id,)).fetchone()
            if not row:
                raise AuthError('Ожидающая заявка не найдена.')
            if approve:
                if not db.execute('UPDATE users SET hwid=? WHERE id=? AND invite IS NOT NULL',
                                  (row['new_hwid'], row['user_id'])).rowcount:
                    raise AuthError('Доступ пользователя отозван.')
                self._revoke_sessions(db, row['user_id'])
            db.execute('UPDATE hardware_requests SET status=? WHERE id=?',
                       ('approved' if approve else 'rejected', request_id))

    def manage_invite(self, code, delete=False):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            code = code.strip().upper()
            if not db.execute('SELECT 1 FROM invites WHERE code=?', (code,)).fetchone():
                raise AuthError('Инвайт не найден.')
            for user in db.execute('SELECT id FROM users WHERE invite=?', (code,)).fetchall():
                self._revoke_sessions(db, user['id'])
            db.execute("UPDATE hardware_requests SET status='rejected' WHERE user_id IN (SELECT id FROM users WHERE invite=?) AND status='reset_requested'", (code,))
            db.execute('UPDATE users SET hwid=NULL WHERE invite=?', (code,))
            if delete:
                db.execute('DELETE FROM invites WHERE code=?', (code,))

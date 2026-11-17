"""Remote access client. Local SQLite is never an authorization fallback."""
import os
import re
import time
from threading import RLock
from urllib.parse import urlsplit
import requests
from core.auth import AuthError, HardwareMismatch
from core.session_vault import SessionVault
from database.store import ROOT, STORAGE


class RemoteAuthService:
    def __init__(self, base_url, *, vault=None, allow_http=False, check_seconds=60):
        url = base_url.strip().rstrip('/')
        parsed = urlsplit(url)
        local_http = allow_http and parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1')
        if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or
                (parsed.scheme != 'https' and not local_http)):
            raise AuthError('Укажите MF_AUTH_SERVER_URL с HTTPS-адресом сервера авторизации. Локальный вход отключён.')
        self.url = url
        self.vault = vault if vault is not None else SessionVault(STORAGE / 'auth_session.bin')
        self.http = requests.Session()
        self.token, self.hwid, self.user = None, None, None
        self.check_seconds, self.checked_at = check_seconds, 0
        self.lock = RLock()

    def _post(self, path, body, *, authenticated=False):
        headers = {'Authorization': f'Bearer {self.token}'} if authenticated else {}
        try:
            response = self.http.post(self.url + path, json=body, headers=headers,
                                      timeout=(3, 10), verify=True, allow_redirects=False)
        except requests.RequestException as exc:
            raise AuthError('Сервер авторизации недоступен. Проверьте интернет и адрес сервера.') from exc
        try:
            result = response.json()
        except ValueError as exc:
            raise AuthError('Сервер авторизации вернул некорректный ответ.') from exc
        if not response.ok or 300 <= response.status_code < 400:
            detail = result.get('detail', {}) if isinstance(result, dict) else {}
            message = detail.get('message', 'Сервер отклонил запрос.') if isinstance(detail, dict) else 'Сервер отклонил запрос.'
            if isinstance(detail, dict) and detail.get('code') == 'hardware_mismatch':
                raise HardwareMismatch(message)
            error = AuthError(message)
            error.status_code = response.status_code
            raise error
        if not isinstance(result, dict):
            raise AuthError('Некорректный ответ сервера авторизации.')
        return result

    def _read_user(self, result):
        user = result.get('user')
        if (not isinstance(user, dict) or type(user.get('id')) is not int or user['id'] < 1 or
                not isinstance(user.get('login'), str) or not 2 <= len(user['login']) <= 40 or
                not re.fullmatch(r'MF-[A-Z0-9]{4}-[A-Z0-9]{4}', str(user.get('invite', ''))) or
                user.get('hwid') != self.hwid):
            raise AuthError('Сервер вернул неверные данные пользователя или HWID.')
        self.user, self.checked_at = user, time.monotonic()
        return user

    def automatic_login(self, hwid):
        self.hwid = hwid
        saved = self.vault.load()
        if not isinstance(saved, dict) or saved.get('server') != self.url or saved.get('hwid') != hwid:
            return None
        token = saved.get('token')
        if not isinstance(token, str) or not 20 <= len(token) <= 256:
            return None
        self.token = token
        try:
            return self._read_user(self._post('/v1/session', {'hwid': hwid}, authenticated=True))
        except AuthError as exc:
            if getattr(exc, 'status_code', None) == 401:
                self.token = None
                self.vault.clear()
                return None
            raise

    def activate(self, login, code, hwid):
        self.hwid = hwid
        result = self._post('/v1/activate', {'login': login.strip(), 'code': code.strip().upper(), 'hwid': hwid})
        token = result.get('token')
        if not isinstance(token, str) or not 20 <= len(token) <= 256:
            raise AuthError('Сервер не выдал токен доступа.')
        user = self._read_user(result)
        self.token = token
        try:
            self.vault.save({'server': self.url, 'hwid': hwid, 'token': token})
        except OSError as exc:
            self.token, self.user, self.checked_at = None, None, 0
            raise AuthError('Не удалось безопасно сохранить сессию Windows. Проверьте доступ к storage/.') from exc
        return user

    def request_reset(self, login, code, hwid, reason):
        return self._post('/v1/reset-requests', {'login': login.strip(), 'code': code.strip().upper(),
                                               'hwid': hwid, 'reason': reason.strip()})

    def ensure_authorized(self):
        with self.lock:
            if not self.token or not self.user:
                raise AuthError('Необходим вход через сервер авторизации.')
            if time.monotonic() - self.checked_at >= self.check_seconds:
                self._read_user(self._post('/v1/session', {'hwid': self.hwid}, authenticated=True))
            return self.user


def create_auth_client():
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    return RemoteAuthService(os.getenv('MF_AUTH_SERVER_URL', ''),
                             allow_http=os.getenv('MF_AUTH_ALLOW_LOCAL_HTTP') == '1')

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import requests
from fastapi.testclient import TestClient
from core.auth import AuthError, HardwareMismatch, AuthService
from core.remote_auth import RemoteAuthService
from database.store import Store
from server.app import create_app

OLD, NEW = 'a' * 64, 'b' * 64


class MemoryVault:
    def __init__(self):
        self.value = None
    def load(self):
        return self.value
    def save(self, value):
        self.value = value
    def clear(self):
        self.value = None


class Bridge:
    def __init__(self, client):
        self.client = client
    def post(self, url, **kwargs):
        assert kwargs['verify'] is True
        assert kwargs['allow_redirects'] is False
        from urllib.parse import urlsplit
        response = self.client.post(urlsplit(url).path, json=kwargs['json'], headers=kwargs['headers'])
        return SimpleNamespace(ok=response.is_success, status_code=response.status_code, json=response.json)


class RemoteAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.app = create_app(self.path / 'server.db')
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.service = self.app.state.auth
        self.code = self.service.local.generate_invites()[0]
        self.vault = MemoryVault()
        self.remote = self.make_remote()

    def make_remote(self):
        remote = RemoteAuthService('https://auth.example', vault=self.vault, check_seconds=0)
        remote.http.close()
        remote.http = Bridge(self.client)
        return remote

    def test_activation_autologin_and_no_plain_token_in_database(self):
        user = self.remote.activate('Reader', self.code, OLD)
        self.assertEqual('Reader', user['login'])
        restored = self.make_remote()
        self.assertEqual(user['id'], restored.automatic_login(OLD)['id'])
        restored.ensure_authorized()
        with self.service.store.connect() as db:
            token_hash = db.execute('SELECT token_hash FROM auth_sessions').fetchone()[0]
        self.assertNotEqual(self.vault.value['token'], token_hash)
        self.assertEqual(64, len(token_hash))

    def test_local_invite_does_not_authorize_against_server(self):
        local = AuthService(Store(self.path / 'local.db'))
        with self.assertRaises(AuthError):
            self.remote.activate('Reader', local.generate_invites()[0], OLD)

    def test_reset_approval_revokes_previous_device_session(self):
        self.remote.activate('Reader', self.code, OLD)
        old_token = self.remote.token
        other = self.make_remote()
        with self.assertRaises(HardwareMismatch):
            other.activate('Reader', self.code, NEW)
        other.request_reset('Reader', self.code, NEW, 'Replacement')
        with self.service.store.connect() as db:
            request_id = db.execute('SELECT id FROM hardware_requests').fetchone()[0]
        self.service.local.review_reset(request_id)
        self.assertEqual(401, self.client.post('/v1/session', json={'hwid': OLD},
                         headers={'Authorization': 'Bearer ' + old_token}).status_code)
        other.activate('Reader', self.code, NEW)
        self.assertEqual(NEW, other.ensure_authorized()['hwid'])

    def test_unbind_and_reactivation_do_not_restore_old_tokens(self):
        self.remote.activate('Reader', self.code, OLD)
        token = self.remote.token
        self.service.local.manage_invite(self.code)
        self.remote.activate('Reader', self.code, OLD)
        self.assertEqual(401, self.client.post('/v1/session', json={'hwid': OLD},
                         headers={'Authorization': 'Bearer ' + token}).status_code)

    def test_expiry_and_wrong_hwid_are_denied(self):
        self.remote.activate('Reader', self.code, OLD)
        headers = {'Authorization': 'Bearer ' + self.remote.token}
        self.assertEqual(401, self.client.post('/v1/session', json={'hwid': NEW}, headers=headers).status_code)
        with self.service.store.connect() as db:
            db.execute('UPDATE auth_sessions SET expires_at=0')
        self.assertIsNone(self.make_remote().automatic_login(OLD))

    def test_network_failure_never_uses_local_authorization(self):
        self.remote.activate('Reader', self.code, OLD)
        self.remote.http.post = Mock(side_effect=requests.ConnectionError('offline'))
        with self.assertRaisesRegex(AuthError, 'недоступен'):
            self.remote.ensure_authorized()

    def test_public_http_and_missing_server_are_denied(self):
        for url in ('', 'http://public.example', 'https://user:secret@auth.example', 'https://auth.example?key=x'):
            with self.assertRaises(AuthError):
                RemoteAuthService(url)
        with self.assertRaises(AuthError):
            RemoteAuthService('http://127.0.0.1:8000')
        dev = RemoteAuthService('http://127.0.0.1:8000', allow_http=True)
        dev.http.close()

    def test_request_size_and_brute_force_limit(self):
        self.assertEqual(413, self.client.post('/v1/activate', content=b'x' * 9000).status_code)
        app = create_app(self.path / 'limited.db', rate_limit=1)
        with TestClient(app) as client:
            client.post('/v1/activate', json={})
            self.assertEqual(429, client.post('/v1/activate', json={}).status_code)

    def test_local_history_identity_is_not_local_authorization(self):
        user = self.remote.activate('Reader', self.code, OLD)
        store = Store(self.path / 'history.db')
        local_user = store.link_remote_user(self.remote.url, user)
        again = store.link_remote_user(self.remote.url, user)
        self.assertEqual(local_user['id'], again['id'])
        self.assertIsNone(AuthService(store).automatic_login(OLD))
        batch = store.create_batch(local_user['id'], 'Volume', ['page.png'])
        self.assertEqual(batch, store.history(again['id'])[0]['id'])


if __name__ == '__main__':
    unittest.main()

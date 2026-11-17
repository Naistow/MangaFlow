import concurrent.futures
import sqlite3
import tempfile
import unittest
from pathlib import Path
from core.auth import AuthService, AuthError, HardwareMismatch
from database.store import Store


class AuthTests(unittest.TestCase):
    def test_migrate_auth_preserves_binding_and_refuses_overwrite(self):
        from server.migrate_auth import migrate
        user = self.auth.activate('Reader', self.code, 'old')
        batch = self.store.create_batch(user['id'], 'Volume', ['one.png'])
        destination = Path(self.temp.name) / 'server.db'
        self.assertEqual((1, 1), migrate(self.store.path, destination))
        remote_store = Store(destination)
        self.assertEqual('Reader', AuthService(remote_store).automatic_login('old')['login'])
        self.assertEqual([], remote_store.history(user['id']))
        self.assertEqual(batch, self.store.history(user['id'])[0]['id'])
        with self.assertRaises(ValueError):
            migrate(self.store.path, destination)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'test.db')
        self.auth = AuthService(self.store)
        self.code = self.auth.generate_invites()[0]

    def test_activation_and_auto_login(self):
        user = self.auth.activate('Reader', self.code.lower(), 'old-machine')
        self.assertEqual(user['id'], self.auth.automatic_login('old-machine')['id'])
        self.assertIsNone(self.auth.automatic_login('new-machine'))
        with self.assertRaises(AuthError):
            self.auth.activate('Thief', self.code, 'new-machine')

    def test_reset_requires_credentials_and_admin_approval(self):
        self.auth.activate('Reader', self.code, 'old')
        with self.assertRaises(HardwareMismatch):
            self.auth.activate('Reader', self.code, 'new')
        with self.assertRaises(AuthError):
            self.auth.request_reset('WrongReader', self.code, 'new', 'Replacement')
        self.auth.request_reset('Reader', self.code, 'new', 'Replacement')
        with self.assertRaises(AuthError):
            self.auth.request_reset('Reader', self.code, 'other', 'Overwrite')
        self.assertIsNone(self.auth.automatic_login('new'))
        with self.store.connect() as db:
            request = db.execute('SELECT id FROM hardware_requests').fetchone()['id']
        self.auth.review_reset(request)
        self.assertIsNone(self.auth.automatic_login('old'))
        self.assertEqual('Reader', self.auth.automatic_login('new')['login'])

    def test_unbind_preserves_login_and_history_delete_revokes(self):
        user = self.auth.activate('Reader', self.code, 'old')
        batch = self.store.create_batch(user['id'], 'Volume', ['page.jpg'])
        self.auth.manage_invite(self.code)
        self.assertIsNone(self.auth.automatic_login('old'))
        self.auth.activate('Reader', self.code, 'new')
        self.auth.manage_invite(self.code, delete=True)
        self.assertIsNone(self.auth.automatic_login('new'))
        self.assertEqual(batch, self.store.history(user['id'])[0]['id'])

    def test_only_one_machine_can_win_concurrent_activation(self):
        def attempt(hwid):
            try:
                self.auth.activate('Reader', self.code, hwid)
                return True
            except AuthError:
                return False
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            self.assertEqual(1, sum(pool.map(attempt, ['a', 'b'])))

    def test_hwid_collision_rolls_back_approval(self):
        self.auth.activate('Reader', self.code, 'old')
        second = self.auth.generate_invites()[0]
        self.auth.activate('Other', second, 'occupied')
        self.auth.request_reset('Reader', self.code, 'occupied', 'Replacement')
        with self.store.connect() as db:
            request = db.execute('SELECT id FROM hardware_requests').fetchone()['id']
        with self.assertRaises(sqlite3.IntegrityError):
            self.auth.review_reset(request)
        self.assertEqual('Reader', self.auth.automatic_login('old')['login'])

    def test_recover_interrupted_keeps_completed_pages(self):
        user = self.auth.activate('Reader', self.code, 'machine')
        batch = self.store.create_batch(user['id'], 'Volume', ['one.png', 'two.png'])
        pages = self.store.pages(batch)
        self.store.update_page(pages[0]['id'], 'completed', 'result.png')
        self.store.update_batch(batch, 'processing')
        self.store.recover_interrupted(user['id'])
        self.assertEqual('failed', self.store.history(user['id'])[0]['status'])
        self.assertEqual(['completed', 'failed'], [p['status'] for p in self.store.pages(batch)])

    def test_statistics_count_successful_pages_and_only_current_user(self):
        user = self.auth.activate('Reader', self.code, 'machine')
        batch = self.store.create_batch(user['id'], 'Volume', ['one.png', 'two.png'])
        page = self.store.pages(batch)[0]
        self.store.update_page(page['id'], 'completed', 'result.png')
        self.store.update_batch(batch, 'partial')
        self.assertEqual((0, 1), self.store.statistics(user['id']))
        self.assertEqual((0, 0), self.store.statistics(user['id'] + 100))
        self.store.update_batch(batch, 'completed')
        self.assertEqual((1, 1), self.store.statistics(user['id']))


if __name__ == '__main__':
    unittest.main()

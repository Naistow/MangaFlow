import os
import tempfile
import unittest
from pathlib import Path
from core.session_vault import SessionVault


@unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
class SessionVaultTests(unittest.TestCase):
    def test_roundtrip_is_encrypted_and_corrupt_session_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.bin'
            vault = SessionVault(path)
            value = {'token': 'test-secret-value', 'server': 'https://example.test'}
            vault.save(value)
            self.assertNotIn(b'test-secret-value', path.read_bytes())
            self.assertEqual(value, vault.load())
            path.write_bytes(b'not-encrypted')
            self.assertIsNone(vault.load())
            vault.clear()
            self.assertFalse(path.exists())

"""Windows user-bound DPAPI storage; never fall back to plaintext tokens."""
import ctypes
import json
import os
from pathlib import Path


class SessionVault:
    def __init__(self, path):
        self.path = Path(path)

    @staticmethod
    def _crypt(data, protect):
        if os.name != 'nt':
            raise OSError('Автоматический вход требует Windows DPAPI.')
        from ctypes import wintypes
        class Blob(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
        buffer = ctypes.create_string_buffer(data)
        source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        output = Blob()
        library = ctypes.WinDLL('crypt32', use_last_error=True)
        function = library.CryptProtectData if protect else library.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        function.restype = wintypes.BOOL
        if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.string_at(output.data, output.size)
        finally:
            free = ctypes.WinDLL('kernel32').LocalFree
            free.argtypes, free.restype = [ctypes.c_void_p], ctypes.c_void_p
            free(output.data)

    def load(self):
        try:
            return json.loads(self._crypt(self.path.read_bytes(), False))
        except (OSError, ValueError):
            return None

    def save(self, value):
        data = self._crypt(json.dumps(value).encode('utf-8'), True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_bytes(data)
        temporary.replace(self.path)

    def clear(self):
        self.path.unlink(missing_ok=True)

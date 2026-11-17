"""Small process-local caches: never retain source images or GPU tensors."""
from collections import OrderedDict
from threading import RLock


class BoundedCache:
    def __init__(self, limit=512):
        self.limit = limit
        self._items = OrderedDict()
        self._lock = RLock()

    def get(self, key):
        with self._lock:
            if key not in self._items:
                return None
            self._items.move_to_end(key)
            return self._items[key]

    def put(self, key, value):
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self.limit:
                self._items.popitem(last=False)

    def clear(self):
        with self._lock:
            self._items.clear()

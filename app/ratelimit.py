"""Tiny in-memory login throttle. One gunicorn worker, so process memory is enough."""
import threading
import time
from collections import defaultdict, deque

_LOCK = threading.Lock()
_FAILS = defaultdict(deque)


def _prune(q, window, at):
    while q and q[0] <= at - window:
        q.popleft()


def is_locked(key, max_failures, window, at=None):
    at = at if at is not None else time.time()
    with _LOCK:
        q = _FAILS[key]
        _prune(q, window, at)
        return len(q) >= max_failures


def record_failure(key, window, at=None):
    at = at if at is not None else time.time()
    with _LOCK:
        q = _FAILS[key]
        _prune(q, window, at)
        q.append(at)


def clear(key):
    with _LOCK:
        _FAILS.pop(key, None)


def reset_all():
    with _LOCK:
        _FAILS.clear()

"""单进程登录失败/注册尝试窗口，计数键有界。"""

import math
from collections import OrderedDict, deque
from time import monotonic


class AuthAttemptLimiter:
    def __init__(self, *, clock=monotonic, window=600, ip_failures=30,
                 account_failures=5, registration_window=600, registration_attempts=10,
                 max_keys=10000):
        self.clock = clock
        self.window, self.ip_failures = window, ip_failures
        self.account_failures = account_failures
        self.registration_window, self.registration_attempts = (
            registration_window, registration_attempts,
        )
        self.max_keys = max_keys
        self._entries = OrderedDict()

    def _entries_for(self, key, window):
        entries = self._entries.pop(key, deque())
        cutoff = self.clock() - window
        while entries and entries[0] <= cutoff:
            entries.popleft()
        self._entries[key] = entries
        while len(self._entries) > self.max_keys:
            self._entries.popitem(last=False)
        return entries

    def _remaining(self, key, window, limit):
        entries = self._entries_for(key, window)
        if len(entries) >= limit:
            return max(1, math.ceil(entries[0] + window - self.clock()))
        return None

    def check_login(self, ip, username):
        return self._remaining(("login_ip", ip), self.window, self.ip_failures) or (
            self._remaining(("login_user", ip, username), self.window, self.account_failures)
        )

    def failed_login(self, ip, username):
        self._entries_for(("login_ip", ip), self.window).append(self.clock())
        self._entries_for(("login_user", ip, username), self.window).append(self.clock())

    def succeeded_login(self, ip, username):
        self._entries.pop(("login_user", ip, username), None)

    def reserve_registration(self, ip):
        remaining = self._remaining(
            ("register_ip", ip), self.registration_window, self.registration_attempts,
        )
        if remaining is None:
            self._entries_for(("register_ip", ip), self.registration_window).append(self.clock())
        return remaining

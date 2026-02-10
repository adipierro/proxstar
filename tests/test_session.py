from proxstar import session as session_mod


class FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = str(value).encode('utf-8') if not isinstance(value, bytes) else value

    def delete(self, key):
        self.store.pop(key, None)


def test_session_start_roundtrip():
    redis = FakeRedis()
    user = 'alice'
    assert session_mod.get_session_start(redis, user) is None
    ts = session_mod.set_session_start(redis, user, start_ts=123.0)
    assert ts == 123.0
    assert session_mod.get_session_start(redis, user) == 123.0


def test_shutdown_roundtrip_and_clear():
    redis = FakeRedis()
    user = 'bob'
    session_mod.set_session_start(redis, user, start_ts=1.0)
    session_mod.set_shutdown_started(redis, user, ts=2.0)
    assert session_mod.get_shutdown_started(redis, user) == 2.0
    session_mod.clear_session(redis, user)
    assert session_mod.get_session_start(redis, user) is None
    assert session_mod.get_shutdown_started(redis, user) is None

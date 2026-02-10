import proxstar as app_mod


def _set_userinfo(username='alice'):
    app_mod.flask_session['userinfo'] = {'preferred_username': username}


def test_session_endpoint_sets_start_when_running(monkeypatch):
    class FakeUser:
        def __init__(self, name):
            self.name = name
            self.rtp = False
            self.active = True

    monkeypatch.setattr(app_mod, 'User', FakeUser)
    monkeypatch.setattr(app_mod, '_get_running_vms', lambda _user: [object()])
    monkeypatch.setattr(app_mod, 'get_session_start', lambda _redis, _user: None)
    monkeypatch.setattr(app_mod, 'set_session_start', lambda _redis, _user: 1000.0)
    monkeypatch.setattr(app_mod, 'clear_session', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_mod.time, 'time', lambda: 1000.0)

    with app_mod.app.test_request_context('/session'):
        _set_userinfo()
        resp = app_mod.session_info()
        data = resp.get_json()
    assert data['running'] is True
    assert data['session_start'] == 1000.0
    assert data['remaining_seconds'] == data['timeout_seconds']


def test_session_endpoint_clears_when_idle(monkeypatch):
    class FakeUser:
        def __init__(self, name):
            self.name = name
            self.rtp = False
            self.active = True

    monkeypatch.setattr(app_mod, 'User', FakeUser)
    cleared = {'called': False}
    monkeypatch.setattr(app_mod, '_get_running_vms', lambda _user: [])
    monkeypatch.setattr(app_mod, 'get_session_start', lambda _redis, _user: 900.0)
    monkeypatch.setattr(
        app_mod, 'clear_session', lambda *_args, **_kwargs: cleared.__setitem__('called', True)
    )
    monkeypatch.setattr(app_mod, 'set_session_start', lambda _redis, _user: 1000.0)
    monkeypatch.setattr(app_mod.time, 'time', lambda: 1000.0)

    with app_mod.app.test_request_context('/session'):
        _set_userinfo()
        resp = app_mod.session_info()
        data = resp.get_json()
    assert data['running'] is False
    assert data['session_start'] is None
    assert cleared['called'] is True


def test_console_page_renders_timer(monkeypatch):
    class FakeUser:
        def __init__(self, name):
            self.name = name
            self.rtp = False
            self.allowed_vms = [100]
            self.active = True

    monkeypatch.setattr(app_mod, 'User', FakeUser)
    monkeypatch.setattr(app_mod, 'connect_proxmox', lambda: object())

    with app_mod.app.test_request_context('/console/100'):
        _set_userinfo()
        resp = app_mod.console_page('100')
        html = resp
        if hasattr(resp, 'data'):
            html = resp.data.decode('utf-8')
    assert 'id="session-timer"' in html
    assert 'id="console-frame"' in html


def test_expire_sessions_endpoint(monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.store = {
                'session_start|alice': b'100',
                'session_start|bob': b'200',
                'session_shutdown|alice': b'50',
            }

        def scan_iter(self, pattern):
            prefix = pattern.replace('*', '')
            for key in list(self.store.keys()):
                if key.startswith(prefix):
                    yield key

        def set(self, key, value):
            self.store[key] = str(value).encode('utf-8')

        def delete(self, key):
            self.store.pop(key, None)

    class FakeUser:
        def __init__(self, name):
            self.name = name
            self.rtp = True
            self.active = True

    class FakeQueue:
        def __init__(self):
            self.calls = []

        def enqueue(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    fake_redis = FakeRedis()
    fake_queue = FakeQueue()

    monkeypatch.setattr(app_mod, 'redis_conn', fake_redis)
    monkeypatch.setattr(app_mod, 'User', FakeUser)
    monkeypatch.setattr(app_mod, 'q', fake_queue)
    monkeypatch.setattr(app_mod.time, 'time', lambda: 1000.0)
    app_mod.app.config['SESSION_TIMEOUT_HOURS'] = 1

    with app_mod.app.test_request_context('/admin/sessions/expire', method='POST'):
        _set_userinfo()
        resp = app_mod.expire_sessions()
        data = resp.get_json()

    assert data['expired'] == 2
    assert 'session_shutdown|alice' not in fake_redis.store
    assert any(call[0][0] == app_mod.enforce_session_timeouts_task for call in fake_queue.calls)

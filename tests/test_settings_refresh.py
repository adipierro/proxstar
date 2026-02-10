import proxstar as app_mod


class _DummyQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, func, job_timeout=None):
        self.calls.append(func.__name__)


def test_settings_refresh_enqueues_pool_cache(monkeypatch):
    dummy = _DummyQueue()
    monkeypatch.setattr(app_mod, 'q', dummy)
    app_mod.app.config['TEMPLATE_POOL'] = ''

    app_mod._enqueue_settings_refresh()

    assert 'generate_pool_cache_task' in dummy.calls
    assert 'sync_templates_task' not in dummy.calls


def test_settings_refresh_enqueues_template_sync_when_enabled(monkeypatch):
    dummy = _DummyQueue()
    monkeypatch.setattr(app_mod, 'q', dummy)
    app_mod.app.config['TEMPLATE_POOL'] = 'templates'

    app_mod._enqueue_settings_refresh()

    assert 'generate_pool_cache_task' in dummy.calls
    assert 'sync_templates_task' in dummy.calls

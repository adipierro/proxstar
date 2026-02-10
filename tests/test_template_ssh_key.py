from proxstar import tasks


class _DummyJob:
    def __init__(self):
        self.meta = {}

    def save_meta(self):
        return None


class _DummyDB:
    def close(self):
        return None


class _DummyVM:
    ssh_keys_called = 0

    def __init__(self, vmid):
        self.id = vmid

    def is_provisioned(self):
        return True

    def set_net_bridge(self, *_args, **_kwargs):
        return None

    def set_cpu(self, *_args, **_kwargs):
        return None

    def set_mem(self, *_args, **_kwargs):
        return None

    def set_ci_user(self, *_args, **_kwargs):
        return None

    def set_ci_ssh_key(self, *_args, **_kwargs):
        _DummyVM.ssh_keys_called += 1
        return None

    def set_ci_network(self, *_args, **_kwargs):
        return None

    def start(self, *_args, **_kwargs):
        return None


def test_template_ssh_key_optional(monkeypatch):
    _DummyVM.ssh_keys_called = 0

    monkeypatch.setattr(tasks, 'connect_proxmox', lambda: object())
    monkeypatch.setattr(tasks, 'ensure_student_network', lambda *_args, **_kwargs: ('vnet', 'subnet'))
    monkeypatch.setattr(tasks, 'clone_vm', lambda *_args, **_kwargs: 100)
    monkeypatch.setattr(tasks, 'get_template', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(tasks, 'get_vm_expire', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, 'get_current_job', lambda: _DummyJob())
    monkeypatch.setattr(tasks, 'connect_db', lambda: _DummyDB())
    monkeypatch.setattr(tasks, 'VM', _DummyVM)

    tasks.setup_template_task(
        template_id=1,
        name='vm-test',
        user='alice',
        ssh_key='',
        cores=1,
        memory=512,
    )

    assert _DummyVM.ssh_keys_called == 0

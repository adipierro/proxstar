import datetime

import pytest

from proxstar import tasks


class FakeJob:
    def __init__(self):
        self.meta = {}

    def save_meta(self):
        return None


class FakeDB:
    def close(self):
        return None


def _fake_connect_db():
    return FakeDB()


def test_create_vm_task_success(monkeypatch):
    job = FakeJob()
    monkeypatch.setattr(tasks, 'get_current_job', lambda: job)
    monkeypatch.setattr(tasks, 'connect_proxmox', lambda: object())
    monkeypatch.setattr(tasks, 'connect_db', _fake_connect_db)
    monkeypatch.setattr(tasks, 'get_node_least_mem', lambda *_args, **_kwargs: 'node1')
    monkeypatch.setattr(tasks, 'ensure_student_network', lambda *_args, **_kwargs: ('vnet1', 'snet'))
    monkeypatch.setattr(tasks.time, 'sleep', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, 'get_vm_expire', lambda *_args, **_kwargs: None)

    created = {}

    def fake_create_vm(proxmox, pool_id, name, cores, memory, disk, iso, vnet, node=None):
        created['args'] = (pool_id, name, cores, memory, disk, iso, vnet, node)
        return 101

    monkeypatch.setattr(tasks, 'create_vm', fake_create_vm)

    class FakeVM:
        def __init__(self, vmid):
            self.vmid = vmid

        def is_provisioned(self):
            return True

    monkeypatch.setattr(tasks, 'VM', FakeVM)

    tasks.create_vm_task('alice', 'vm1', '2', '1024', '10', 'iso')
    assert job.meta['status'] == 'complete'
    assert created['args'][6] == 'vnet1'
    assert created['args'][7] == 'node1'


def test_create_vm_task_sdn_failure_marks_job(monkeypatch):
    job = FakeJob()
    monkeypatch.setattr(tasks, 'get_current_job', lambda: job)
    monkeypatch.setattr(tasks, 'connect_proxmox', lambda: object())
    monkeypatch.setattr(tasks, 'connect_db', _fake_connect_db)
    monkeypatch.setattr(tasks, 'get_node_least_mem', lambda *_args, **_kwargs: 'node1')

    def fail_sdn(*_args, **_kwargs):
        raise RuntimeError('sdn failed')

    monkeypatch.setattr(tasks, 'ensure_student_network', fail_sdn)

    with pytest.raises(RuntimeError):
        tasks.create_vm_task('alice', 'vm1', '2', '1024', '10', 'iso')
    assert job.meta['status'] == 'failed: sdn'


def test_delete_vm_task_stops_then_deletes(monkeypatch):
    state = {'status': 'running', 'stop_called': 0, 'delete_called': 0}

    class FakeVM:
        def __init__(self, vmid):
            self.vmid = vmid

        @property
        def status(self):
            return state['status']

        def stop(self):
            state['stop_called'] += 1
            state['status'] = 'stopped'

        def delete(self):
            state['delete_called'] += 1

    monkeypatch.setattr(tasks, 'VM', FakeVM)
    monkeypatch.setattr(tasks, 'connect_db', _fake_connect_db)
    monkeypatch.setattr(tasks.time, 'sleep', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, 'delete_vm_expire', lambda _db, vmid: state.setdefault('expire', vmid))

    tasks.delete_vm_task(55)
    assert state['stop_called'] == 1
    assert state['delete_called'] == 1
    assert state['expire'] == 55


def test_setup_template_task_clones_and_applies_cloud_init(monkeypatch):
    job = FakeJob()
    monkeypatch.setattr(tasks, 'get_current_job', lambda: job)
    monkeypatch.setattr(tasks, 'connect_proxmox', lambda: object())
    monkeypatch.setattr(tasks, 'connect_db', _fake_connect_db)
    monkeypatch.setattr(tasks, 'get_node_least_mem', lambda *_args, **_kwargs: 'node1')
    monkeypatch.setattr(tasks, 'ensure_student_network', lambda *_args, **_kwargs: ('vnet1', 'snet'))
    monkeypatch.setattr(tasks, 'get_template', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, 'get_vm_expire', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks.time, 'sleep', lambda *_args, **_kwargs: None)
    tasks.app.config['TEMPLATE_CLONE_FULL'] = False

    clone_args = {}

    def fake_clone_vm(proxmox, template_id, name, pool_id, full_clone=True, target=None):
        clone_args['args'] = (template_id, name, pool_id, full_clone, target)
        return 202

    monkeypatch.setattr(tasks, 'clone_vm', fake_clone_vm)

    class FakeVM:
        last_instance = None

        def __init__(self, vmid):
            self.vmid = vmid
            self.calls = []
            FakeVM.last_instance = self

        def is_provisioned(self):
            return True

        def set_net_bridge(self, net, bridge):
            self.calls.append(('set_net_bridge', net, bridge))

        def set_cpu(self, cores):
            self.calls.append(('set_cpu', cores))

        def set_mem(self, mem):
            self.calls.append(('set_mem', mem))

        def set_ci_user(self, user):
            self.calls.append(('set_ci_user', user))

        def set_ci_ssh_key(self, key):
            self.calls.append(('set_ci_ssh_key', key))

        def set_ci_network(self):
            self.calls.append(('set_ci_network',))

        def start(self):
            self.calls.append(('start',))

    monkeypatch.setattr(tasks, 'VM', FakeVM)

    tasks.setup_template_task(7, 'vm1', 'alice', 'ssh-rsa AAA', '2', '1024')
    assert clone_args['args'][3] is False
    assert job.meta['status'] == 'completed'
    assert ('set_net_bridge', 'net0', 'vnet1') in FakeVM.last_instance.calls
    assert ('set_ci_ssh_key', 'ssh-rsa AAA') in FakeVM.last_instance.calls
    assert ('start',) in FakeVM.last_instance.calls


def test_process_expiring_vms_task_deletes_and_stops(monkeypatch):
    tasks.app.config['ENABLE_VM_EXPIRATION'] = True

    base_date = datetime.date(2024, 1, 15)

    class FakeDate(datetime.date):
        @classmethod
        def today(cls):
            return base_date

    monkeypatch.setattr(tasks.datetime, 'date', FakeDate)
    monkeypatch.setattr(tasks, 'connect_proxmox', lambda: object())
    monkeypatch.setattr(tasks, 'connect_db', _fake_connect_db)
    monkeypatch.setattr(tasks, 'get_pools', lambda *_args, **_kwargs: ['alice'])

    class FakeUser:
        def __init__(self, name, db_session=None):
            self.name = name
            self.vms = [{'vmid': 1}, {'vmid': 2}, {'vmid': 3}]

    monkeypatch.setattr(tasks, 'User', FakeUser)

    vm_state = {
        1: {'expire': base_date - datetime.timedelta(days=8), 'stopped': 0},
        2: {'expire': base_date - datetime.timedelta(days=1), 'stopped': 0},
        3: {'expire': base_date + datetime.timedelta(days=5), 'stopped': 0},
    }

    class FakeVM:
        def __init__(self, vmid):
            self.id = vmid
            self.name = f'vm{vmid}'
            self._data = vm_state[vmid]

        @property
        def expire(self):
            return self._data['expire']

        def stop(self):
            self._data['stopped'] += 1

    monkeypatch.setattr(tasks, 'VM', FakeVM)

    deleted = []

    def fake_delete_vm_task(vmid):
        deleted.append(vmid)

    monkeypatch.setattr(tasks, 'delete_vm_task', fake_delete_vm_task)

    class FakeRedis:
        def __init__(self, *_args, **_kwargs):
            pass

        def get(self, _key):
            return b'token'

        def delete(self, _key):
            return None

    monkeypatch.setattr(tasks, 'Redis', FakeRedis)
    monkeypatch.setattr(tasks, 'delete_vnc_target', lambda *_args, **_kwargs: None)

    tasks.process_expiring_vms_task()

    assert deleted == [1]
    assert vm_state[2]['stopped'] == 1
    assert vm_state[3]['stopped'] == 0


def test_enforce_session_timeouts_sets_start(monkeypatch):
    tasks.app.config['PROXMOX_HOSTS'] = ['node1']
    tasks.app.config['SESSION_TIMEOUT_HOURS'] = 1
    tasks.app.config['SESSION_SHUTDOWN_GRACE_MINUTES'] = 5
    from proxstar import session as session_mod

    class FakeRedis:
        def __init__(self, *_args, **_kwargs):
            self.store = {}

        def get(self, key):
            return self.store.get(key)

        def set(self, key, value):
            self.store[key] = str(value).encode('utf-8')

        def delete(self, key):
            self.store.pop(key, None)

    fake_redis = FakeRedis()
    monkeypatch.setattr(tasks, 'Redis', lambda *_args, **_kwargs: fake_redis)
    monkeypatch.setattr(tasks, 'connect_proxmox', lambda: object())
    monkeypatch.setattr(tasks, 'connect_db', _fake_connect_db)
    monkeypatch.setattr(tasks, 'get_pools', lambda *_args, **_kwargs: ['alice'])

    class FakeUser:
        def __init__(self, name, db_session=None):
            self.name = name
            self.vms = [{'vmid': 1}]

    monkeypatch.setattr(tasks, 'User', FakeUser)

    class FakeVM:
        def __init__(self, vmid):
            self.vmid = vmid
            self.status = 'running'

    monkeypatch.setattr(tasks, 'VM', FakeVM)
    monkeypatch.setattr(
        tasks, 'set_session_start', lambda redis, user: session_mod.set_session_start(redis, user, start_ts=1000.0)
    )

    tasks.enforce_session_timeouts_task()
    assert fake_redis.get('session_start|alice') == b'1000.0'


def test_enforce_session_timeouts_shutdown_then_stop(monkeypatch):
    tasks.app.config['PROXMOX_HOSTS'] = ['node1']
    tasks.app.config['SESSION_TIMEOUT_HOURS'] = 1
    tasks.app.config['SESSION_SHUTDOWN_GRACE_MINUTES'] = 5

    class FakeRedis:
        def __init__(self, *_args, **_kwargs):
            self.store = {
                'session_start|alice': b'0',
                'session_shutdown|alice': b'100',
            }

        def get(self, key):
            return self.store.get(key)

        def set(self, key, value):
            self.store[key] = str(value).encode('utf-8')

        def delete(self, key):
            self.store.pop(key, None)

    fake_redis = FakeRedis()
    monkeypatch.setattr(tasks, 'Redis', lambda *_args, **_kwargs: fake_redis)
    monkeypatch.setattr(tasks, 'connect_proxmox', lambda: object())
    monkeypatch.setattr(tasks, 'connect_db', _fake_connect_db)
    monkeypatch.setattr(tasks, 'get_pools', lambda *_args, **_kwargs: ['alice'])

    class FakeUser:
        def __init__(self, name, db_session=None):
            self.name = name
            self.vms = [{'vmid': 1}]

    monkeypatch.setattr(tasks, 'User', FakeUser)

    vm_state = {'shutdown': 0, 'stop': 0}

    class FakeVM:
        def __init__(self, vmid):
            self.vmid = vmid
            self.status = 'running'

        def shutdown(self):
            vm_state['shutdown'] += 1

        def stop(self):
            vm_state['stop'] += 1

    monkeypatch.setattr(tasks, 'VM', FakeVM)
    monkeypatch.setattr(tasks.time, 'time', lambda: 10000.0)

    tasks.enforce_session_timeouts_task()
    assert vm_state['shutdown'] == 0
    assert vm_state['stop'] == 1

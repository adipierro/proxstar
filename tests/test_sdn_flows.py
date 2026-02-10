from proxstar import sdn as sdn_mod


class FakeStudentNetwork:
    def __init__(self, username, vnet, subnet):
        self.id = None
        self.username = username
        self.vnet = vnet
        self.subnet = subnet


class FakeDB:
    def __init__(self):
        self.added = []
        self.deleted = []
        self.committed = 0
        self.rolled_back = 0
        self.next_id = 1

    def add(self, obj):
        self.added.append(obj)

    def delete(self, obj):
        self.deleted.append(obj)

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def flush(self):
        for obj in self.added:
            if getattr(obj, 'id', None) is None:
                obj.id = self.next_id
                self.next_id += 1


def _noop(*_args, **_kwargs):
    return None


def test_sdn_existing_entry_ready_skips_apply(monkeypatch):
    entry = FakeStudentNetwork('alice', 's1', '10.0.0.0/24')
    db = FakeDB()

    monkeypatch.setattr(sdn_mod, 'get_student_network', lambda _db, _user: entry)
    monkeypatch.setattr(sdn_mod, '_vnet_ready', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sdn_mod, 'ensure_zone', _noop)

    calls = {'vnet': 0, 'subnet': 0, 'firewall': 0, 'apply': 0}
    monkeypatch.setattr(sdn_mod, 'ensure_vnet', lambda *_args, **_kwargs: calls.__setitem__('vnet', calls['vnet'] + 1))
    monkeypatch.setattr(sdn_mod, 'ensure_subnet', lambda *_args, **_kwargs: calls.__setitem__('subnet', calls['subnet'] + 1))
    monkeypatch.setattr(sdn_mod, 'ensure_firewall_group_rule', lambda *_args, **_kwargs: calls.__setitem__('firewall', calls['firewall'] + 1))
    monkeypatch.setattr(sdn_mod, 'require_sdn_apply', lambda *_args, **_kwargs: calls.__setitem__('apply', calls['apply'] + 1))

    vnet, subnet = sdn_mod.ensure_student_network(db, {}, 'alice', proxmox=object())
    assert (vnet, subnet) == ('s1', '10.0.0.0/24')
    assert calls == {'vnet': 0, 'subnet': 0, 'firewall': 0, 'apply': 0}


def test_sdn_existing_entry_reconciles_and_applies(monkeypatch):
    entry = FakeStudentNetwork('bob', 's2', '10.0.1.0/24')
    db = FakeDB()

    monkeypatch.setattr(sdn_mod, 'get_student_network', lambda _db, _user: entry)
    monkeypatch.setattr(sdn_mod, '_vnet_ready', lambda *_args, **_kwargs: False)
    monkeypatch.setattr(sdn_mod, 'ensure_zone', _noop)

    calls = {'vnet': 0, 'subnet': 0, 'firewall': 0, 'apply': 0}
    monkeypatch.setattr(sdn_mod, 'ensure_vnet', lambda *_args, **_kwargs: calls.__setitem__('vnet', calls['vnet'] + 1))
    monkeypatch.setattr(sdn_mod, 'ensure_subnet', lambda *_args, **_kwargs: calls.__setitem__('subnet', calls['subnet'] + 1))
    monkeypatch.setattr(sdn_mod, 'ensure_firewall_group_rule', lambda *_args, **_kwargs: calls.__setitem__('firewall', calls['firewall'] + 1))
    monkeypatch.setattr(sdn_mod, 'require_sdn_apply', lambda *_args, **_kwargs: calls.__setitem__('apply', calls['apply'] + 1))

    vnet, subnet = sdn_mod.ensure_student_network(db, {}, 'bob', proxmox=object())
    assert (vnet, subnet) == ('s2', '10.0.1.0/24')
    assert calls == {'vnet': 1, 'subnet': 1, 'firewall': 1, 'apply': 1}


def test_sdn_adopts_existing_vnet_by_alias(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(sdn_mod, 'get_student_network', lambda _db, _user: None)
    monkeypatch.setattr(sdn_mod, '_find_vnet_by_alias', lambda *_args, **_kwargs: 's9')
    monkeypatch.setattr(sdn_mod, '_get_vnet_subnets', lambda *_args, **_kwargs: [{'subnet': '10.0.9.0/24'}])
    monkeypatch.setattr(sdn_mod, 'ensure_zone', _noop)
    monkeypatch.setattr(sdn_mod, 'Student_Network', FakeStudentNetwork)

    vnet, subnet = sdn_mod.ensure_student_network(db, {}, 'carol', proxmox=object())
    assert (vnet, subnet) == ('s9', '10.0.9.0/24')
    assert db.committed == 1
    assert db.added[0].username == 'carol'
    assert db.added[0].vnet == 's9'


def test_sdn_collision_retries_allocation(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(sdn_mod, 'get_student_network', lambda _db, _user: None)
    monkeypatch.setattr(sdn_mod, '_find_vnet_by_alias', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sdn_mod, 'ensure_zone', _noop)
    monkeypatch.setattr(sdn_mod, 'Student_Network', FakeStudentNetwork)

    allocations = iter(['10.0.0.0/24', '10.0.1.0/24'])
    monkeypatch.setattr(sdn_mod, 'allocate_student_subnet', lambda *_args, **_kwargs: next(allocations))

    monkeypatch.setattr(sdn_mod, 'ensure_vnet', _noop)
    monkeypatch.setattr(sdn_mod, 'ensure_firewall_group_rule', _noop)
    monkeypatch.setattr(sdn_mod, 'require_sdn_apply', _noop)

    calls = {'subnet': 0}

    def fake_ensure_subnet(*_args, **_kwargs):
        calls['subnet'] += 1
        if calls['subnet'] == 1:
            raise sdn_mod.SubnetCollision('10.0.0.0/24')
        return None

    monkeypatch.setattr(sdn_mod, 'ensure_subnet', fake_ensure_subnet)

    vnet, subnet = sdn_mod.ensure_student_network(db, {}, 'dave', proxmox=object())
    assert subnet == '10.0.1.0/24'
    assert db.rolled_back == 1
    assert db.committed == 1

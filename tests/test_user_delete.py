from flask import session

from proxstar import app
from proxstar import user as user_mod


class _FakeUserRecord:
    def __init__(self, userid, groups_map, deleted):
        self._userid = userid
        self._groups_map = groups_map
        self._deleted = deleted

    def get(self):
        return {'groups': self._groups_map.get(self._userid, '')}

    def delete(self):
        self._deleted.append(self._userid)


class _FakeUsers:
    def __init__(self, users, groups_map, deleted):
        self._users = users
        self._groups_map = groups_map
        self._deleted = deleted

    def get(self):
        return self._users

    def __call__(self, userid):
        return _FakeUserRecord(userid, self._groups_map, self._deleted)


class _FakeAccess:
    def __init__(self, users, groups_map, deleted):
        self.users = _FakeUsers(users, groups_map, deleted)


class _FakePools:
    def __init__(self):
        self.deleted = []

    def __call__(self, poolid):
        return self

    def delete(self):
        self.deleted.append('deleted')


class _FakeProxmox:
    def __init__(self, users, groups_map, deleted):
        self.access = _FakeAccess(users, groups_map, deleted)
        self.pools = _FakePools()


def test_user_delete_skips_protected_groups(monkeypatch):
    app.config['PROXMOX_USER_REALM'] = 'pve'
    app.config['PROXMOX_PROTECTED_GROUPS'] = ['admins']

    deleted = []
    users = [{'userid': 'alice@pve'}]
    groups_map = {'alice@pve': 'admins'}
    fake = _FakeProxmox(users, groups_map, deleted)

    monkeypatch.setattr(user_mod, 'connect_proxmox', lambda: fake)

    with app.test_request_context():
        session['userinfo'] = {'preferred_username': 'alice'}
        user = user_mod.User('alice')
        user.delete()

    assert deleted == []


def test_user_delete_removes_unprotected_user(monkeypatch):
    app.config['PROXMOX_USER_REALM'] = 'pve'
    app.config['PROXMOX_PROTECTED_GROUPS'] = ['admins']

    deleted = []
    users = [{'userid': 'bob@pve'}]
    groups_map = {'bob@pve': 'students'}
    fake = _FakeProxmox(users, groups_map, deleted)

    monkeypatch.setattr(user_mod, 'connect_proxmox', lambda: fake)

    with app.test_request_context():
        session['userinfo'] = {'preferred_username': 'bob'}
        user = user_mod.User('bob')
        user.delete()

    assert deleted == ['bob@pve']

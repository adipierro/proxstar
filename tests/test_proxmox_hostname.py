from proxstar.proxmox import is_hostname_available, is_hostname_valid


class _FakeResources:
    def get(self, type=None):
        return [{'name': 'alpha'}, {'name': 'beta'}]


class _FakeCluster:
    def __init__(self):
        self.resources = _FakeResources()


class _FakeProxmox:
    def __init__(self):
        self.cluster = _FakeCluster()


def test_is_hostname_valid():
    assert is_hostname_valid('vm-1') is True
    assert is_hostname_valid('a') is False
    assert is_hostname_valid('-bad') is False
    assert is_hostname_valid('bad-') is False
    assert is_hostname_valid('bad_name') is False


def test_is_hostname_available():
    proxmox = _FakeProxmox()
    assert is_hostname_available(proxmox, 'alpha') is False
    assert is_hostname_available(proxmox, 'gamma') is True

import pytest

from proxstar import sdn as sdn_mod


def test_allocate_student_subnet_first_available(monkeypatch):
    monkeypatch.setattr(sdn_mod, 'get_assigned_student_subnets', lambda db: ['10.0.0.0/26'])
    subnet = sdn_mod.allocate_student_subnet(db=None, base_cidr='10.0.0.0/24', prefix_len=26)
    assert subnet == '10.0.0.64/26'


def test_allocate_student_subnet_exhausted(monkeypatch):
    monkeypatch.setattr(
        sdn_mod,
        'get_assigned_student_subnets',
        lambda db: ['10.0.0.0/26', '10.0.0.64/26', '10.0.0.128/26', '10.0.0.192/26'],
    )
    with pytest.raises(RuntimeError):
        sdn_mod.allocate_student_subnet(db=None, base_cidr='10.0.0.0/24', prefix_len=26)

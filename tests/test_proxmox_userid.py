from proxstar import app
from proxstar.proxmox import get_proxmox_userid


def test_get_proxmox_userid_without_realm():
    app.config['PROXMOX_USER_REALM'] = ''
    with app.app_context():
        assert get_proxmox_userid('alice') == 'alice'


def test_get_proxmox_userid_with_realm():
    app.config['PROXMOX_USER_REALM'] = 'pve'
    with app.app_context():
        assert get_proxmox_userid('alice') == 'alice@pve'

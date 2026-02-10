import math

from flask import current_app as app
from proxmoxer import ProxmoxAPI

from proxstar import logging
from proxstar.db import get_ignored_pools
from proxstar.ldapdb import is_user


def connect_proxmox(host=None):
    if host:
        try:
            return attempt_proxmox_connection(host)
        except:
            logging.error(f'unable to connect to {host}')
            raise

    for host_candidate in app.config['PROXMOX_HOSTS']:
        try:
            return attempt_proxmox_connection(host_candidate)
        except:
            if app.config['PROXMOX_HOSTS'].index(host_candidate) == (
                len(app.config['PROXMOX_HOSTS']) - 1
            ):
                logging.error('unable to connect to any of the given Proxmox servers')
                raise


def attempt_proxmox_connection(host):
    proxmox = ProxmoxAPI(
        host,
        user=app.config['PROXMOX_USER'],
        token_name=app.config['PROXMOX_TOKEN_NAME'],
        token_value=app.config['PROXMOX_TOKEN_VALUE'],
        verify_ssl=False,
    )
    proxmox.version.get()
    return proxmox


def get_node_least_mem(proxmox):
    nodes = proxmox.nodes.get()
    sorted_nodes = sorted(nodes, key=lambda x: ('mem' not in x, x.get('mem', None)))
    return sorted_nodes[0]['node']


def get_free_vmid(proxmox):
    return proxmox.cluster.nextid.get()


def get_vm_node(proxmox, vmid):
    for vm in proxmox.cluster.resources.get(type='vm'):
        if vm['vmid'] == int(vmid):
            return vm['node']
    return None


def get_isos(proxmox, storage):
    isos = []
    first_node = app.config['PROXMOX_HOSTS'][0].split('.')[0]  # Get the name of the first node.
    for iso in proxmox.nodes(first_node).storage(storage).content.get():
        isos.append(iso['volid'].split('/')[1])
    return isos


def get_pools(proxmox, db):
    ignored_pools = get_ignored_pools(db)
    pools = []
    for pool in proxmox.pools.get():
        poolid = pool['poolid']
        if poolid not in ignored_pools and is_user(poolid):
            pools.append(poolid)
    pools = sorted(pools)
    return pools


def get_templates_from_pool(proxmox, pool_name):
    if not pool_name:
        return None
    try:
        pool = proxmox.pools(pool_name).get()
        members = pool.get('members', [])
    except Exception as e:  # pylint: disable=broad-except
        logging.error('Failed to load template pool %s: %s', pool_name, e)
        return None
    templates = []
    for member in members:
        if member.get('type') != 'qemu':
            continue
        is_template = member.get('template')
        if str(is_template).lower() not in ('1', 'true'):
            continue
        vmid = member.get('vmid')
        if vmid is None:
            continue
        name = member.get('name') or str(vmid)
        maxdisk = member.get('maxdisk')
        disk_gb = None
        if maxdisk is not None:
            disk_gb = int(math.ceil(maxdisk / (1024 ** 3)))
        templates.append({'id': int(vmid), 'name': name, 'disk': disk_gb})
    return templates


def get_proxmox_userid(username):
    realm = app.config.get('PROXMOX_USER_REALM', '')
    if realm:
        return f'{username}@{realm}'
    return username


def is_hostname_valid(name):
    if not name or len(name) < 2:
        return False
    if not name.replace('-', '').isalnum() or name.startswith('-') or name.endswith('-'):
        return False
    return True


def is_hostname_available(proxmox, name):
    if not is_hostname_valid(name):
        return False
    for vm in proxmox.cluster.resources.get(type='vm'):
        if vm.get('name') == name:
            return False
    return True

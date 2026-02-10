import ipaddress
import logging
import re
import time

from proxstar.db import get_assigned_student_subnets, get_student_network
from proxstar.models import Student_Network
from proxstar.proxmox import connect_proxmox


def _get_zone_name(config):
    return config.get('SDN_ZONE') or 'proxstar-sdn'


def _list_zones(proxmox):
    try:
        return proxmox.cluster.sdn.zones.get()
    except Exception as e:  # pylint: disable=broad-except
        logging.error(f'Failed to list SDN zones: {e}')
        return []


def _list_vnets(proxmox):
    try:
        return proxmox.cluster.sdn.vnets.get()
    except Exception as e:  # pylint: disable=broad-except
        logging.error(f'Failed to list SDN vnets: {e}')
        return []


def _list_subnets(proxmox):
    try:
        return proxmox.cluster.sdn.subnets.get()
    except Exception:
        subnets = []
        for vnet in _list_vnets(proxmox):
            vnet_name = vnet.get('vnet')
            if not vnet_name:
                continue
            try:
                subnets.extend(proxmox.cluster.sdn.vnets(vnet_name).subnets.get())
            except Exception:
                continue
        return subnets


def _list_firewall_rules(proxmox, vnet_name):
    try:
        return proxmox.cluster.sdn.vnets(vnet_name).firewall.rules.get()
    except Exception as e:  # pylint: disable=broad-except
        logging.error(f'Failed to list firewall rules for vnet {vnet_name}: {e}')
        return []


def _get_vnet_subnets(proxmox, vnet_name):
    try:
        return proxmox.cluster.sdn.vnets(vnet_name).subnets.get()
    except Exception as e:  # pylint: disable=broad-except
        logging.error(f'Failed to list subnets for vnet {vnet_name}: {e}')
        return []


def _find_vnet_by_alias(proxmox, alias):
    for vnet in _list_vnets(proxmox):
        if vnet.get('alias') == alias:
            return vnet.get('vnet')
    return None


def _sanitize_vnet_id(raw, max_len):
    cleaned = re.sub(r'[^A-Za-z0-9]', '', raw)
    if not cleaned:
        cleaned = 'vnet'
    if cleaned[0].isdigit():
        cleaned = f'vnet{cleaned}'
    return cleaned[:max_len]


def _encode_base36(num):
    alphabet = '0123456789abcdefghijklmnopqrstuvwxyz'
    if num == 0:
        return '0'
    result = ''
    while num > 0:
        num, rem = divmod(num, 36)
        result = alphabet[rem] + result
    return result


def _build_vnet_id(prefix, numeric_id, max_len):
    base = _encode_base36(numeric_id)
    prefix = re.sub(r'[^A-Za-z0-9]', '', prefix or 'v')
    if not prefix:
        prefix = 'v'
    if prefix[0].isdigit():
        prefix = f'v{prefix}'
    vnet = f'{prefix}{base}'
    return vnet[:max_len]


def require_sdn_apply(proxmox, config=None):
    if not apply_sdn(proxmox, config=config):
        raise RuntimeError('Unable to apply SDN changes via API')


def _wait_for_task(proxmox, upid, timeout=60, interval=2):
    try:
        node = upid.split(':', 2)[1]
    except Exception as e:  # pylint: disable=broad-except
        raise RuntimeError(f'Unable to parse node from task id {upid}: {e}')
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = proxmox.nodes(node).tasks(upid).status.get()
        if status.get('status') == 'stopped':
            exitstatus = status.get('exitstatus', '')
            if exitstatus and exitstatus != 'OK':
                raise RuntimeError(f'SDN apply task failed: {exitstatus}')
            return True
        time.sleep(interval)
    raise RuntimeError(f'SDN apply task timed out after {timeout}s: {upid}')


def wait_for_vnet_bridge(proxmox, node, vnet_name, timeout=60, interval=2):
    if not node:
        raise RuntimeError('No target node supplied for SDN bridge check')
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for iface in proxmox.nodes(node).network.get():
                if iface.get('iface') == vnet_name or iface.get('name') == vnet_name:
                    return True
        except Exception as e:  # pylint: disable=broad-except
            logging.warning('Failed to check SDN bridge on %s: %s', node, e)
        time.sleep(interval)
    raise RuntimeError(f'SDN bridge {vnet_name} not present on node {node}')


def _get_existing_subnets(proxmox):
    existing = set()
    if proxmox is None:
        return existing
    for subnet in _list_subnets(proxmox):
        cidr = subnet.get('subnet')
        if cidr:
            existing.add(str(cidr))
    return existing


def ensure_zone(config, proxmox=None):
    if proxmox is None:
        proxmox = connect_proxmox()
    zone_name = _get_zone_name(config)
    for zone in _list_zones(proxmox):
        if zone.get('zone') == zone_name:
            return zone_name

    zone_type = config.get('SDN_ZONE_TYPE', 'simple')
    payload = {
        'zone': zone_name,
        'type': zone_type,
    }
    bridge = config.get('SDN_ZONE_BRIDGE')
    if zone_type in ('vlan', 'qinq'):
        if not bridge:
            raise RuntimeError('SDN_ZONE_BRIDGE is required for vlan/qinq zones')
        payload['bridge'] = bridge
    ipam = config.get('SDN_ZONE_IPAM')
    if ipam:
        payload['ipam'] = ipam
    mtu = config.get('SDN_ZONE_MTU')
    if mtu:
        payload['mtu'] = mtu
    dns = config.get('SDN_ZONE_DNS')
    if dns:
        payload['dns'] = dns

    proxmox.cluster.sdn.zones.post(**payload)
    require_sdn_apply(proxmox, config=config)
    return zone_name


def ensure_vnet(config, vnet_name, proxmox=None, alias=None):
    if proxmox is None:
        proxmox = connect_proxmox()
    zone_name = _get_zone_name(config)
    for vnet in _list_vnets(proxmox):
        if vnet.get('vnet') == vnet_name:
            return vnet_name

    alias_prefix = config.get('SDN_VNET_ALIAS_PREFIX', 'Proxstar')
    payload = {
        'vnet': vnet_name,
        'zone': zone_name,
        'alias': alias or f'{alias_prefix} {vnet_name}',
    }
    vlan_id = config.get('SDN_VNET_VLAN')
    if vlan_id:
        payload['tag'] = int(vlan_id)

    proxmox.cluster.sdn.vnets.post(**payload)
    require_sdn_apply(proxmox, config=config)
    return vnet_name


def ensure_subnet(config, vnet_name, subnet_cidr, proxmox=None):
    if proxmox is None:
        proxmox = connect_proxmox()

    existing = _get_vnet_subnets(proxmox, vnet_name)

    for subnet in existing:
        if subnet.get('subnet') == subnet_cidr:
            return subnet_cidr

    network = ipaddress.ip_network(subnet_cidr)
    gateway = str(next(network.hosts()))

    dhcp_start = config.get('SDN_DHCP_START_OFFSET', 50)
    dhcp_end = config.get('SDN_DHCP_END_OFFSET', 200)
    dhcp_start_ip = ipaddress.ip_address(int(network.network_address) + dhcp_start)
    dhcp_end_ip = ipaddress.ip_address(int(network.network_address) + dhcp_end)
    dhcp_range = f'start-address={dhcp_start_ip},end-address={dhcp_end_ip}'

    payload = {
        'type': 'subnet',
        'subnet': subnet_cidr,
        'gateway': gateway,
        'dhcp-range': [dhcp_range],
    }

    snat = config.get('SDN_SUBNET_SNAT')
    if snat is not None:
        payload['snat'] = int(bool(snat))

    dns = config.get('SDN_SUBNET_DNS')
    if dns:
        payload['dns'] = dns

    try:
        proxmox.cluster.sdn.vnets(vnet_name).subnets.post(**payload)
    except Exception as e:  # pylint: disable=broad-except
        # If the subnet was created concurrently, treat it as success.
        if 'already defined' in str(e):
            for subnet in _get_vnet_subnets(proxmox, vnet_name):
                if subnet.get('subnet') == subnet_cidr:
                    require_sdn_apply(proxmox, config=config)
                    return subnet_cidr
        raise
    require_sdn_apply(proxmox, config=config)
    return subnet_cidr


def ensure_firewall_group_rule(config, vnet_name, proxmox=None):
    if proxmox is None:
        proxmox = connect_proxmox()
    group = config.get('SDN_VNET_FIREWALL_GROUP', '')
    if not group:
        return None
    for rule in _list_firewall_rules(proxmox, vnet_name):
        if rule.get('type') == 'group' and rule.get('action') == group:
            return group
    payload = {
        'type': 'group',
        'action': group,
    }
    proxmox.cluster.sdn.vnets(vnet_name).firewall.rules.post(**payload)
    require_sdn_apply(proxmox, config=config)
    return group


def apply_sdn(proxmox, config=None):
    apply_timeout = 60
    if config is not None:
        apply_timeout = int(config.get('SDN_APPLY_TIMEOUT', 60))
    for attempt in (
        lambda: proxmox.cluster.sdn.apply.post(),
        lambda: proxmox.cluster.sdn.apply.put(),
        lambda: proxmox.cluster.sdn.post(),
    ):
        try:
            result = attempt()
            upid = None
            if isinstance(result, dict):
                upid = result.get('data') or result.get('upid')
            if upid:
                _wait_for_task(proxmox, upid, timeout=apply_timeout)
            return True
        except Exception as e:  # pylint: disable=broad-except
            logging.warning('SDN apply attempt failed: %s', e)
            continue
    logging.warning('Unable to apply SDN changes via API. Apply manually in Proxmox.')
    return False


def allocate_student_subnet(db, base_cidr, prefix_len, proxmox=None, reserved=None):
    base = ipaddress.ip_network(base_cidr)
    assigned = set(get_assigned_student_subnets(db))
    assigned.update(_get_existing_subnets(proxmox))
    if reserved:
        assigned.update(reserved)
    for subnet in base.subnets(new_prefix=prefix_len):
        if str(subnet) not in assigned:
            return str(subnet)
    raise RuntimeError('No available subnets in SDN base CIDR')


def ensure_student_network(db, config, user, proxmox=None):
    entry = get_student_network(db, user)
    if proxmox is None:
        proxmox = connect_proxmox()

    zone_name = ensure_zone(config, proxmox)
    max_len = int(config.get('SDN_VNET_MAX_LEN', 8))
    alias_prefix = config.get('SDN_VNET_ALIAS_PREFIX', 'Proxstar')
    vnet_alias = f'{alias_prefix} {user}'

    def _save_entry(existing_entry, vnet_name, subnet_cidr):
        if existing_entry:
            existing_entry.vnet = vnet_name
            existing_entry.subnet = subnet_cidr
        else:
            existing_entry = Student_Network(
                username=user,
                vnet=vnet_name,
                subnet=subnet_cidr,
            )
            db.add(existing_entry)
        db.commit()
        return vnet_name, subnet_cidr

    if not entry:
        adopt_vnet = _find_vnet_by_alias(proxmox, vnet_alias)
        if adopt_vnet:
            subnets = _get_vnet_subnets(proxmox, adopt_vnet)
            for subnet in subnets:
                subnet_cidr = subnet.get('subnet')
                if subnet_cidr:
                    return _save_entry(entry, adopt_vnet, subnet_cidr)

    if entry:
        vnet_name = entry.vnet
        subnet = entry.subnet
        try:
            ensure_vnet(config, vnet_name, proxmox, alias=vnet_alias)
            ensure_subnet(config, vnet_name, subnet, proxmox)
            ensure_firewall_group_rule(config, vnet_name, proxmox)
            require_sdn_apply(proxmox, config=config)
        except Exception as e:
            if 'already defined' in str(e):
                adopt_vnet = _find_vnet_by_alias(proxmox, vnet_alias)
                if adopt_vnet:
                    subnets = _get_vnet_subnets(proxmox, adopt_vnet)
                    for subnet in subnets:
                        subnet_cidr = subnet.get('subnet')
                        if subnet_cidr:
                            return _save_entry(entry, adopt_vnet, subnet_cidr)
                db.delete(entry)
                db.commit()
            else:
                raise
        else:
            return vnet_name, subnet

    max_attempts = int(config.get('SDN_SUBNET_ALLOCATE_ATTEMPTS', 5))
    reserved = set()
    for _ in range(max_attempts):
        subnet = allocate_student_subnet(
            db,
            config.get('SDN_BASE_CIDR', '10.100.0.0/16'),
            int(config.get('SDN_STUDENT_PREFIX', 24)),
            proxmox=proxmox,
            reserved=reserved,
        )

        entry = Student_Network(username=user, vnet='pending', subnet=subnet)
        db.add(entry)
        db.flush()

        vnet_prefix = config.get('SDN_VNET_ID_PREFIX', 's')
        vnet_name = _build_vnet_id(vnet_prefix, entry.id, max_len)

        try:
            ensure_vnet(config, vnet_name, proxmox, alias=vnet_alias)
            ensure_subnet(config, vnet_name, subnet, proxmox)
            ensure_firewall_group_rule(config, vnet_name, proxmox)
            require_sdn_apply(proxmox, config=config)
        except Exception as e:
            db.rollback()
            if 'already defined' in str(e):
                reserved.add(subnet)
                continue
            raise

        entry.vnet = vnet_name
        db.commit()
        return entry.vnet, entry.subnet

    raise RuntimeError('Unable to allocate a unique SDN subnet')

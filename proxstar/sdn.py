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


def _get_vnet(proxmox, vnet_name):
    for vnet in _list_vnets(proxmox):
        if vnet.get('vnet') == vnet_name:
            return vnet
    return None


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




def _get_existing_subnets(proxmox):
    existing = set()
    if proxmox is None:
        return existing
    for subnet in _list_subnets(proxmox):
        cidr = subnet.get('subnet')
        if cidr:
            existing.add(str(cidr))
    return existing


class SubnetCollision(RuntimeError):
    def __init__(self, subnet_cidr):
        super().__init__(f'SDN subnet {subnet_cidr} already defined elsewhere')
        self.subnet_cidr = subnet_cidr


def _is_pending(obj):
    if not isinstance(obj, dict):
        return False
    pending = obj.get('pending')
    if isinstance(pending, str):
        return pending.lower() in ('1', 'true', 'yes')
    if isinstance(pending, int):
        return pending == 1
    if pending is True:
        return True
    state = obj.get('state') or obj.get('status')
    if isinstance(state, str) and state.lower() == 'pending':
        return True
    return False


def _vnet_ready(config, proxmox, vnet_name, subnet_cidr):
    vnet = _get_vnet(proxmox, vnet_name)
    if not vnet:
        logging.info('SDN: vnet %s not found', vnet_name)
        return False
    if _is_pending(vnet):
        logging.info('SDN: vnet %s is pending', vnet_name)
        return False
    zone_name = _get_zone_name(config)
    if vnet.get('zone') != zone_name:
        logging.info(
            'SDN: vnet %s zone mismatch (got %s, expected %s)',
            vnet_name,
            vnet.get('zone'),
            zone_name,
        )
        return False
    if subnet_cidr:
        has_subnet = False
        vnet_subnets = _get_vnet_subnets(proxmox, vnet_name)
        for subnet in vnet_subnets:
            if subnet.get('subnet') == subnet_cidr:
                if _is_pending(subnet):
                    logging.info('SDN: subnet %s on vnet %s is pending', subnet_cidr, vnet_name)
                    return False
                has_subnet = True
                break
        if not has_subnet:
            logging.info(
                'SDN: subnet %s missing on vnet %s (seen=%s)',
                subnet_cidr,
                vnet_name,
                [s.get('subnet') for s in vnet_subnets],
            )
            return False
    group = config.get('SDN_VNET_FIREWALL_GROUP', '')
    if group:
        has_group = any(
            rule.get('type') == 'group' and rule.get('action') == group
            for rule in _list_firewall_rules(proxmox, vnet_name)
        )
        if not has_group:
            logging.info('SDN: firewall group %s missing on vnet %s', group, vnet_name)
            return False
    return True


def ensure_zone(config, proxmox=None, apply_now=True):
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
    if apply_now:
        require_sdn_apply(proxmox, config=config)
    return zone_name


def ensure_vnet(config, vnet_name, proxmox=None, alias=None, apply_now=True):
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
    if apply_now:
        require_sdn_apply(proxmox, config=config)
    return vnet_name


def ensure_subnet(config, vnet_name, subnet_cidr, proxmox=None, apply_now=True):
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
                    if apply_now:
                        require_sdn_apply(proxmox, config=config)
                    return subnet_cidr
            for subnet in _list_subnets(proxmox):
                if subnet.get('subnet') == subnet_cidr and subnet.get('vnet') == vnet_name:
                    if apply_now:
                        require_sdn_apply(proxmox, config=config)
                    return subnet_cidr
            raise SubnetCollision(subnet_cidr)
        raise
    if apply_now:
        require_sdn_apply(proxmox, config=config)
    return subnet_cidr


def ensure_firewall_group_rule(config, vnet_name, proxmox=None, apply_now=True):
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
    if apply_now:
        require_sdn_apply(proxmox, config=config)
    return group


def apply_sdn(proxmox, config=None):
    apply_timeout = 60
    payload = {}
    if config is not None:
        apply_timeout = int(config.get('SDN_APPLY_TIMEOUT', 60))
        lock_token = config.get('SDN_LOCK_TOKEN', '')
        if lock_token:
            payload['lock-token'] = lock_token
            payload['release-lock'] = 1 if config.get('SDN_RELEASE_LOCK', True) else 0
    for attempt in (
        # lambda: proxmox.cluster.sdn.apply.post(),
        # lambda: proxmox.cluster.sdn.apply.put(),
        lambda: proxmox.cluster.sdn.put(**payload),
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

    ensure_zone(config, proxmox, apply_now=False)
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
        logging.info('SDN: no existing network entry for %s, attempting adopt', user)
        adopt_vnet = _find_vnet_by_alias(proxmox, vnet_alias)
        if adopt_vnet:
            logging.info('SDN: adopting vnet %s for %s via alias', adopt_vnet, user)
            subnets = _get_vnet_subnets(proxmox, adopt_vnet)
            for subnet in subnets:
                subnet_cidr = subnet.get('subnet')
                if subnet_cidr:
                    return _save_entry(entry, adopt_vnet, subnet_cidr)

    if entry:
        vnet_name = entry.vnet
        subnet = entry.subnet
        logging.info('SDN: found entry for %s -> vnet %s subnet %s', user, vnet_name, subnet)
        if _vnet_ready(config, proxmox, vnet_name, subnet):
            logging.info('SDN: vnet %s already ready for %s', vnet_name, user)
            return vnet_name, subnet
        try:
            ensure_vnet(config, vnet_name, proxmox, alias=vnet_alias, apply_now=False)
            ensure_subnet(config, vnet_name, subnet, proxmox, apply_now=False)
            ensure_firewall_group_rule(config, vnet_name, proxmox, apply_now=False)
            require_sdn_apply(proxmox, config=config)
        except SubnetCollision as e:
            logging.warning('SDN: subnet collision for %s (%s)', user, e.subnet_cidr)
            adopt_vnet = _find_vnet_by_alias(proxmox, vnet_alias)
            if adopt_vnet:
                logging.info('SDN: adopting vnet %s after collision for %s', adopt_vnet, user)
                subnets = _get_vnet_subnets(proxmox, adopt_vnet)
                for subnet_entry in subnets:
                    subnet_cidr = subnet_entry.get('subnet')
                    if subnet_cidr:
                        return _save_entry(entry, adopt_vnet, subnet_cidr)
            db.delete(entry)
            db.commit()
            entry = None
            reserved = {e.subnet_cidr}
        except Exception:
            raise
        else:
            logging.info('SDN: vnet %s configured for %s', vnet_name, user)
            return vnet_name, subnet

    max_attempts = int(config.get('SDN_SUBNET_ALLOCATE_ATTEMPTS', 5))
    reserved = locals().get('reserved', set())
    for _ in range(max_attempts):
        subnet = allocate_student_subnet(
            db,
            config.get('SDN_BASE_CIDR', '10.100.0.0/16'),
            int(config.get('SDN_STUDENT_PREFIX', 24)),
            proxmox=proxmox,
            reserved=reserved,
        )
        logging.info('SDN: allocated subnet %s for %s', subnet, user)

        entry = Student_Network(username=user, vnet='pending', subnet=subnet)
        db.add(entry)
        db.flush()

        vnet_prefix = config.get('SDN_VNET_ID_PREFIX', 's')
        vnet_name = _build_vnet_id(vnet_prefix, entry.id, max_len)

        try:
            ensure_vnet(config, vnet_name, proxmox, alias=vnet_alias, apply_now=False)
            ensure_subnet(config, vnet_name, subnet, proxmox, apply_now=False)
            ensure_firewall_group_rule(config, vnet_name, proxmox, apply_now=False)
            require_sdn_apply(proxmox, config=config)
        except SubnetCollision as e:
            db.rollback()
            reserved.add(e.subnet_cidr)
            logging.warning('SDN: subnet collision on %s, retrying', e.subnet_cidr)
            continue
        except Exception:
            db.rollback()
            raise

        entry.vnet = vnet_name
        db.commit()
        logging.info('SDN: created vnet %s subnet %s for %s', vnet_name, subnet, user)
        return entry.vnet, entry.subnet

    raise RuntimeError('Unable to allocate a unique SDN subnet')

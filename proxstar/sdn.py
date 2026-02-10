import ipaddress
import logging

from proxstar.db import get_assigned_student_subnets, get_student_network, add_student_network
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
    apply_sdn(proxmox)
    return zone_name


def ensure_vnet(config, vnet_name, proxmox=None):
    if proxmox is None:
        proxmox = connect_proxmox()
    zone_name = _get_zone_name(config)
    for vnet in _list_vnets(proxmox):
        if vnet.get('vnet') == vnet_name:
            return vnet_name

    alias = config.get('SDN_VNET_ALIAS_PREFIX', 'Proxstar')
    payload = {
        'vnet': vnet_name,
        'zone': zone_name,
        'alias': f'{alias} {vnet_name}',
    }
    vlan_id = config.get('SDN_VNET_VLAN')
    if vlan_id:
        payload['tag'] = int(vlan_id)

    proxmox.cluster.sdn.vnets.post(**payload)
    apply_sdn(proxmox)
    return vnet_name


def ensure_subnet(config, vnet_name, subnet_cidr, proxmox=None):
    if proxmox is None:
        proxmox = connect_proxmox()

    try:
        existing = proxmox.cluster.sdn.vnets(vnet_name).subnets.get()
    except Exception as e:  # pylint: disable=broad-except
        logging.error(f'Failed to list subnets for vnet {vnet_name}: {e}')
        existing = []

    for subnet in existing:
        if subnet.get('subnet') == subnet_cidr:
            return subnet_cidr

    network = ipaddress.ip_network(subnet_cidr)
    gateway = str(next(network.hosts()))

    dhcp_start = config.get('SDN_DHCP_START_OFFSET', 50)
    dhcp_end = config.get('SDN_DHCP_END_OFFSET', 200)
    dhcp_range = f'{ipaddress.ip_address(int(network.network_address) + dhcp_start)}-{ipaddress.ip_address(int(network.network_address) + dhcp_end)}'

    payload = {
        'subnet': subnet_cidr,
        'gateway': gateway,
        'dhcp-range': dhcp_range,
    }

    snat = config.get('SDN_SUBNET_SNAT')
    if snat is not None:
        payload['snat'] = int(bool(snat))

    dns = config.get('SDN_SUBNET_DNS')
    if dns:
        payload['dns'] = dns

    proxmox.cluster.sdn.vnets(vnet_name).subnets.post(**payload)
    apply_sdn(proxmox)
    return subnet_cidr


def apply_sdn(proxmox):
    for attempt in (
        lambda: proxmox.cluster.sdn.post(),
        lambda: proxmox.cluster.sdn.apply.post(),
        lambda: proxmox.cluster.sdn.apply.put(),
    ):
        try:
            attempt()
            return True
        except Exception:  # pylint: disable=broad-except
            continue
    logging.warning('Unable to apply SDN changes via API. Apply manually in Proxmox.')
    return False


def allocate_student_subnet(db, base_cidr, prefix_len):
    base = ipaddress.ip_network(base_cidr)
    assigned = set(get_assigned_student_subnets(db))
    for subnet in base.subnets(new_prefix=prefix_len):
        if str(subnet) not in assigned:
            return str(subnet)
    raise RuntimeError('No available subnets in SDN base CIDR')


def ensure_student_network(db, config, user, proxmox=None):
    entry = get_student_network(db, user)
    if entry:
        return entry.vnet, entry.subnet

    if proxmox is None:
        proxmox = connect_proxmox()

    zone_name = ensure_zone(config, proxmox)
    vnet_name = f"{config.get('SDN_VNET_PREFIX', 'student')}-{user}"

    subnet = allocate_student_subnet(
        db,
        config.get('SDN_BASE_CIDR', '10.100.0.0/16'),
        int(config.get('SDN_STUDENT_PREFIX', 24)),
    )

    ensure_vnet(config, vnet_name, proxmox)
    ensure_subnet(config, vnet_name, subnet, proxmox)

    entry = add_student_network(db, user, vnet_name, subnet)
    return entry.vnet, entry.subnet

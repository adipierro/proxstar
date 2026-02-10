from os import environ

# Proxstar
VM_EXPIRE_MONTHS = int(environ.get('PROXSTAR_VM_EXPIRE_MONTHS', '3'))
VNC_CLEANUP_TOKEN = environ.get('PROXSTAR_VNC_CLEANUP_TOKEN', '')
DEFAULT_CPU_LIMIT = int(environ.get('PROXSTAR_DEFAULT_CPU_LIMIT', '8'))
DEFAULT_MEM_LIMIT = int(environ.get('PROXSTAR_DEFAULT_MEM_LIMIT', '8'))
DEFAULT_DISK_LIMIT = int(environ.get('PROXSTAR_DEFAULT_DISK_LIMIT', '250'))

# Development options
# If you're an RTP and want to see a normal user's homepage view, set this to True.
FORCE_STANDARD_USER = environ.get('PROXSTAR_FORCE_STANDARD_USER', 'False').lower() in (
    'true',
    '1',
    't',
)


# Flask
IP = environ.get('PROXSTAR_IP', '0.0.0.0')
PORT = environ.get('PROXSTAR_PORT', '5000')
SERVER_NAME = environ.get('PROXSTAR_SERVER_NAME', 'localhost')
SERVER_SCHEME = environ.get('PROXSTAR_SERVER_SCHEME', 'http')
SECRET_KEY = environ.get('PROXSTAR_SECRET_KEY', '')
TESTING = environ.get('PROXSTAR_TESTING', 'False').lower() in ('true', '1', 't')
DISABLE_AUTH = environ.get('PROXSTAR_DISABLE_AUTH', 'False').lower() in ('true', '1', 't')
LOCAL_USER = environ.get('PROXSTAR_LOCAL_USER', 'localuser')
LOCAL_GROUPS = [g.strip() for g in environ.get('PROXSTAR_LOCAL_GROUPS', '').split(',') if g.strip()]

# OIDC
OIDC_ISSUER = environ.get('PROXSTAR_OIDC_ISSUER', 'https://example.com/oidc')
OIDC_CLIENT_ID = environ.get('PROXSTAR_CLIENT_ID', 'proxstar')
OIDC_CLIENT_SECRET = environ.get('PROXSTAR_CLIENT_SECRET', '')
OIDC_GROUPS_CLAIM = environ.get('PROXSTAR_OIDC_GROUPS_CLAIM', 'groups')
OIDC_ADMIN_GROUPS = [g.strip() for g in environ.get('PROXSTAR_OIDC_ADMIN_GROUPS', '').split(',') if g.strip()]
OIDC_ACTIVE_GROUPS = [g.strip() for g in environ.get('PROXSTAR_OIDC_ACTIVE_GROUPS', '').split(',') if g.strip()]
OIDC_STUDENT_GROUPS = [g.strip() for g in environ.get('PROXSTAR_OIDC_STUDENT_GROUPS', '').split(',') if g.strip()]
OIDC_PROFILE_IMAGE_CLAIM = environ.get('PROXSTAR_OIDC_PROFILE_IMAGE_CLAIM', 'picture')

# Proxmox
PROXMOX_HOSTS = [
    host.strip() for host in environ.get('PROXSTAR_PROXMOX_HOSTS', '').split(',') if host.strip()
]
PROXMOX_USER = environ.get('PROXSTAR_PROXMOX_USER', '')
PROXMOX_TOKEN_NAME = environ.get('PROXSTAR_PROXMOX_TOKEN_NAME', '')
PROXMOX_TOKEN_VALUE = environ.get('PROXSTAR_PROXMOX_TOKEN_VALUE', '')
PROXMOX_ISO_STORAGE = environ.get('PROXSTAR_PROXMOX_ISO_STORAGE', 'nfs-iso')
PROXMOX_VM_STORAGE = environ.get('PROXSTAR_PROXMOX_VM_STORAGE', 'ceph')
PROXMOX_USER_REALM = environ.get('PROXSTAR_PROXMOX_USER_REALM', '')
PROXMOX_NODE_DOMAIN = environ.get('PROXSTAR_PROXMOX_NODE_DOMAIN', '')
PROXMOX_PROTECTED_GROUPS = [
    g.strip() for g in environ.get('PROXSTAR_PROXMOX_PROTECTED_GROUPS', '').split(',') if g.strip()
]

# Proxmox SDN
SDN_ZONE = environ.get('PROXSTAR_SDN_ZONE', '')
SDN_ZONE_TYPE = environ.get('PROXSTAR_SDN_ZONE_TYPE', 'simple')
SDN_ZONE_BRIDGE = environ.get('PROXSTAR_SDN_ZONE_BRIDGE', '')
SDN_ZONE_IPAM = environ.get('PROXSTAR_SDN_ZONE_IPAM', '')
SDN_ZONE_MTU = environ.get('PROXSTAR_SDN_ZONE_MTU', '')
SDN_ZONE_DNS = environ.get('PROXSTAR_SDN_ZONE_DNS', '')
SDN_VNET_PREFIX = environ.get('PROXSTAR_SDN_VNET_PREFIX', 'student')
SDN_VNET_ID_PREFIX = environ.get('PROXSTAR_SDN_VNET_ID_PREFIX', 's')
SDN_VNET_ALIAS_PREFIX = environ.get('PROXSTAR_SDN_VNET_ALIAS_PREFIX', 'Proxstar')
SDN_VNET_VLAN = environ.get('PROXSTAR_SDN_VNET_VLAN', '')
SDN_VNET_MAX_LEN = int(environ.get('PROXSTAR_SDN_VNET_MAX_LEN', '8'))
SDN_VNET_FIREWALL_GROUP = environ.get('PROXSTAR_SDN_VNET_FIREWALL_GROUP', '')
SDN_APPLY_TIMEOUT = int(environ.get('PROXSTAR_SDN_APPLY_TIMEOUT', '60'))
SDN_SUBNET_ALLOCATE_ATTEMPTS = int(environ.get('PROXSTAR_SDN_SUBNET_ALLOCATE_ATTEMPTS', '5'))
SDN_BASE_CIDR = environ.get('PROXSTAR_SDN_BASE_CIDR', '10.100.0.0/16')
SDN_STUDENT_PREFIX = int(environ.get('PROXSTAR_SDN_STUDENT_PREFIX', '24'))
SDN_DHCP_START_OFFSET = int(environ.get('PROXSTAR_SDN_DHCP_START_OFFSET', '50'))
SDN_DHCP_END_OFFSET = int(environ.get('PROXSTAR_SDN_DHCP_END_OFFSET', '200'))
SDN_SUBNET_SNAT = environ.get('PROXSTAR_SDN_SUBNET_SNAT', '').lower() in ('true', '1', 't')
SDN_SUBNET_DNS = environ.get('PROXSTAR_SDN_SUBNET_DNS', '')

# Session timeouts
SESSION_TIMEOUT_HOURS = float(environ.get('PROXSTAR_SESSION_TIMEOUT_HOURS', '6'))
SESSION_SHUTDOWN_GRACE_MINUTES = int(
    environ.get('PROXSTAR_SESSION_SHUTDOWN_GRACE_MINUTES', '5')
)
SESSION_CHECK_INTERVAL_SECONDS = int(
    environ.get('PROXSTAR_SESSION_CHECK_INTERVAL_SECONDS', '300')
)
ENABLE_VM_EXPIRATION = environ.get('PROXSTAR_ENABLE_VM_EXPIRATION', 'False').lower() in (
    'true',
    '1',
    't',
)

# Template cloning
TEMPLATE_CLONE_FULL = environ.get('PROXSTAR_TEMPLATE_CLONE_FULL', 'True').lower() in (
    'true',
    '1',
    't',
)
TEMPLATE_POOL = environ.get('PROXSTAR_TEMPLATE_POOL', '')

# LDAP
LDAP_BIND_DN = environ.get('PROXSTAR_LDAP_BIND_DN', '')
LDAP_BIND_PW = environ.get('PROXSTAR_LDAP_BIND_PW', '')

# DB
SQLALCHEMY_DATABASE_URI = environ.get('PROXSTAR_SQLALCHEMY_DATABASE_URI', '')

# REDIS
REDIS_HOST = environ.get('PROXSTAR_REDIS_HOST', 'localhost')
RQ_DASHBOARD_REDIS_URL = (
    "redis://" + environ.get('PROXSTAR_REDIS_HOST', 'localhost') + ":" +
    environ.get('PROXSTAR_REDIS_PORT', '6379') + "/0"
)
REDIS_PORT = int(environ.get('PROXSTAR_REDIS_PORT', '6379'))

# VNC
WEBSOCKIFY_PATH = environ.get('PROXSTAR_WEBSOCKIFY_PATH', '/usr/local/bin/websockify')
WEBSOCKIFY_TARGET_FILE = environ.get('PROXSTAR_WEBSOCKIFY_TARGET_FILE', '/opt/proxstar/targets')
VNC_HOST = environ.get('PROXSTAR_VNC_HOST', 'localhost')
VNC_PORT = environ.get('PROXSTAR_VNC_PORT', '443')
WEBSOCKIFY_PORT = environ.get('PROXSTAR_WEBSOCKIFY_PORT', '8081')

# UI
THEME_CSS_URL = environ.get('PROXSTAR_THEME_CSS_URL', 'https://stackpath.bootstrapcdn.com/bootstrap/4.3.1/css/bootstrap.min.css')
FAVICON_URL = environ.get('PROXSTAR_FAVICON_URL', '')
PROFILE_IMAGE_URL_BASE = environ.get('PROXSTAR_PROFILE_IMAGE_URL_BASE', '')

# SENTRY
# If you set the sentry dsn locally, make sure you use the local-dev or some
# other local environment, so we can separate local errors from production
SENTRY_DSN = environ.get('PROXSTAR_SENTRY_DSN', '')
RQ_SENTRY_DSN = environ.get('PROXSTAR_SENTRY_DSN', '')
SENTRY_ENV = environ.get('PROXSTAR_SENTRY_ENV', 'local-dev')

# DATADOG RUM
DD_CLIENT_TOKEN = environ.get('PROXSTAR_DD_CLIENT_TOKEN', '')
DD_APP_ID = environ.get('PROXSTAR_DD_APP_ID', '')

# GUNICORN
TIMEOUT = environ.get('PROXSTAR_TIMEOUT', 120)

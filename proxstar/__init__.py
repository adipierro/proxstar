import os
import json
import time
import atexit
import logging
import subprocess
import psutil

# from gunicorn_conf import start_websockify
import rq_dashboard
from rq import Queue
from redis import Redis
from rq_scheduler import Scheduler
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    abort,
    url_for,
    jsonify,
    Response,
)
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.rq import RqIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from proxstar import util
from proxstar.db import (
    Base,
    datetime,
    get_pool_cache,
    set_user_usage_limits,
    get_template,
    get_templates,
    get_allowed_users,
    add_ignored_pool,
    delete_ignored_pool,
    add_allowed_user,
    delete_allowed_user,
    get_template_disk,
    set_template_info,
    add_shared_pool,
    get_shared_pool,
    get_shared_pools,
)
from proxstar.ldapdb import is_rtp
from proxstar.vnc import (
    add_vnc_target,
    get_vnc_targets,
    delete_vnc_target,
    stop_websockify,
    open_vnc_session,
)
from proxstar.auth import get_auth
from proxstar.util import gen_password
from proxstar.proxmox import (
    connect_proxmox,
    get_isos,
    get_pools,
    get_ignored_pools,
    is_hostname_available,
    is_hostname_valid,
)
from proxstar.session import (
    clear_session,
    get_session_start,
    set_session_start,
)
from proxstar.sdn import ensure_student_network

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.INFO)

app = Flask(__name__)
app.config.from_object(rq_dashboard.default_settings)
if os.path.exists(os.path.join(app.config.get('ROOT_DIR', os.getcwd()), 'config_local.py')):
    config = os.path.join(app.config.get('ROOT_DIR', os.getcwd()), 'config_local.py')
else:
    config = os.path.join(app.config.get('ROOT_DIR', os.getcwd()), 'config.py')
app.config.from_pyfile(config)
app.config['GIT_REVISION'] = (
    subprocess.check_output('git rev-parse --short HEAD', shell=True).decode('utf-8').rstrip()
)

testing = app.config.get('TESTING', False)
disable_auth = app.config.get('DISABLE_AUTH', False)

# Sentry setup
if not testing:
    sentry_sdk.init(
        dsn=app.config['SENTRY_DSN'],
        integrations=[FlaskIntegration(), RqIntegration(), SqlalchemyIntegration()],
        environment=app.config['SENTRY_ENV'],
    )


class _DummyAuth:
    def oidc_auth(self, *args, **kwargs):
        def decorator(fn):
            return fn

        return decorator

    def oidc_logout(self, fn):
        return fn


class _LocalAuth(_DummyAuth):
    def __init__(self, app):
        self.app = app

    def oidc_auth(self, *args, **kwargs):
        def decorator(fn):
            from functools import wraps

            @wraps(fn)
            def wrapped(*f_args, **f_kwargs):
                if 'userinfo' not in session:
                    session['userinfo'] = {
                        'preferred_username': self.app.config.get('LOCAL_USER', 'localuser')
                    }
                    claim = self.app.config.get('OIDC_GROUPS_CLAIM', 'groups')
                    local_groups = self.app.config.get('LOCAL_GROUPS', [])
                    if local_groups:
                        session['userinfo'][claim] = local_groups
                return fn(*f_args, **f_kwargs)

            return wrapped

        return decorator

    def oidc_logout(self, fn):
        from functools import wraps

        @wraps(fn)
        def wrapped(*f_args, **f_kwargs):
            session.clear()
            return fn(*f_args, **f_kwargs)

        return wrapped


if testing:
    auth = _DummyAuth()
elif disable_auth:
    auth = _LocalAuth(app)
else:
    auth = get_auth(app)

redis_conn = Redis(app.config['REDIS_HOST'], app.config['REDIS_PORT'])
q = Queue(connection=redis_conn, default_timeout=360)
scheduler = Scheduler(connection=redis_conn)

engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'])
Base.metadata.bind = engine
DBSession = sessionmaker(bind=engine)
db = DBSession()

from proxstar.vm import VM
from proxstar.user import User
from proxstar.tasks import (
    generate_pool_cache_task,
    process_expiring_vms_task,
    cleanup_vnc_task,
    delete_vm_task,
    create_vm_task,
    setup_template_task,
    enforce_session_timeouts_task,
)

if not testing:
    if 'generate_pool_cache' not in scheduler:
        logging.info('adding generate pool cache task to scheduler')
        scheduler.schedule(
            id='generate_pool_cache',
            scheduled_time=datetime.datetime.utcnow(),
            func=generate_pool_cache_task,
            interval=90,
        )

    if app.config.get('ENABLE_VM_EXPIRATION') and 'process_expiring_vms' not in scheduler:
        logging.info('adding process expiring VMs task to scheduler')
        scheduler.cron('0 5 * * *', id='process_expiring_vms', func=process_expiring_vms_task)

    if 'cleanup_vnc' not in scheduler:
        logging.info('adding cleanup VNC task to scheduler')
        scheduler.schedule(
            id='cleanup_vnc',
            scheduled_time=datetime.datetime.utcnow(),
            func=cleanup_vnc_task,
            interval=3600,
        )

    if 'enforce_session_timeouts' not in scheduler:
        logging.info('adding session timeout enforcement task to scheduler')
        scheduler.schedule(
            id='enforce_session_timeouts',
            scheduled_time=datetime.datetime.utcnow(),
            func=enforce_session_timeouts_task,
            interval=app.config['SESSION_CHECK_INTERVAL_SECONDS'],
        )


def add_rq_dashboard_auth(blueprint):
    @blueprint.before_request
    @auth.oidc_auth('default')
    def rq_dashboard_auth(*args, **kwargs):  # pylint: disable=unused-argument,unused-variable
        user = User(session['userinfo']['preferred_username'])
        if not user.rtp:
            abort(403)


if not testing:
    rq_dashboard_blueprint = rq_dashboard.blueprint
    add_rq_dashboard_auth(rq_dashboard_blueprint)
    rq_dashboard.web.setup_rq_connection(app)
    app.register_blueprint(rq_dashboard_blueprint, url_prefix='/rq')


def _get_running_vms(user):
    running = []
    for vm in user.vms:
        if 'vmid' not in vm:
            continue
        vm_obj = VM(vm['vmid'])
        if vm_obj.status in ('running', 'paused'):
            running.append(vm_obj)
    return running


def _ensure_session_started(user):
    if get_session_start(redis_conn, user.name) is None:
        set_session_start(redis_conn, user.name)


def _clear_session_if_idle(user):
    if not _get_running_vms(user):
        clear_session(redis_conn, user.name)


def _get_claim(info, path):
    if not path:
        return None
    cur = info
    for part in path.split('.'):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _profile_image_url(username=None):
    info = session.get('userinfo', {})
    current_username = info.get('preferred_username')
    if username is None:
        username = current_username
    if username and username == current_username:
        claim = app.config.get('OIDC_PROFILE_IMAGE_CLAIM', 'picture')
        url = _get_claim(info, claim)
        if isinstance(url, str) and url:
            return url
    base = app.config.get('PROFILE_IMAGE_URL_BASE', '')
    if base and username:
        return f"{base.rstrip('/')}/{username}"
    return None


@app.context_processor
def inject_profile_helpers():
    return {'profile_image_url': _profile_image_url}


def _node_fqdn(node):
    domain = app.config.get('PROXMOX_NODE_DOMAIN', '')
    if domain:
        return f'{node}.{domain}'
    return node


@app.errorhandler(404)
def not_found(e):
    try:
        user = User(session['userinfo']['preferred_username'])
        return render_template('404.html', user=user, e=e), 404
    except KeyError as exception:
        logging.warning('Missing userinfo in session for 404: %s', exception)
        return render_template('404.html', user='chom', e=e), 404


@app.errorhandler(403)
def forbidden(e):
    try:
        user = User(session['userinfo']['preferred_username'])
        return render_template('403.html', user=user, e=e), 403
    except KeyError as exception:
        logging.warning('Missing userinfo in session for 403: %s', exception)
        return render_template('403.html', user='chom', e=e), 403


@app.route('/')
@app.route('/user/<string:user_view>')
@auth.oidc_auth('default')
def list_vms(user_view=None):
    user = User(session['userinfo']['preferred_username'])
    connect_proxmox()
    if app.config['FORCE_STANDARD_USER']:
        user.rtp = False
    if user_view:
        if not user.rtp:
            abort(403)
        user_view = User(user_view)
        vms = user_view.vms
        for pending_vm in user_view.pending_vms:
            vm = next((vm for vm in vms if vm['name'] == pending_vm['name']), None)
            if vm:
                vms[vms.index(vm)]['status'] = pending_vm['status']
                vms[vms.index(vm)]['pending'] = True
            else:
                vms.append(pending_vm)
    else:
        if user.active:
            vms = user.vms
            for pending_vm in user.pending_vms:
                vm = next((vm for vm in vms if vm['name'] == pending_vm['name']), None)
                if vm:
                    vms[vms.index(vm)]['status'] = pending_vm['status']
                    vms[vms.index(vm)]['pending'] = True
                else:
                    vms.append(pending_vm)
        else:
            vms = 'INACTIVE'
    return render_template('list_vms.html', user=user, external_view=user_view, vms=vms)


@app.route('/pool/shared/<string:name>')
@auth.oidc_auth('default')
def list_shared_vms(name=None):
    user = User(session['userinfo']['preferred_username'])
    pool = get_shared_pool(db, name)
    if pool:
        if user.name in pool.members or user.rtp:
            proxmox = connect_proxmox()
            vms = proxmox.pools(pool.name).get()['members']
        else:
            return 'Not Member of Pool', 403
    else:
        return 'Pool does not exist', 400
    if app.config['FORCE_STANDARD_USER']:
        user.rtp = False
    return render_template('list_vms.html', user=user, external_view=pool, vms=vms)


@app.route('/pools')
def list_pools():
    user = User(session['userinfo']['preferred_username'])
    if app.config['FORCE_STANDARD_USER']:
        user.rtp = False
    proxmox = connect_proxmox()
    user_pools = get_pool_cache(db) if user.rtp else []
    shared_pools = map(
        lambda pool: {
            'name': pool.name,
            'members': pool.members,
            'vms': proxmox.pools(pool.name).get()['members'],
        },
        get_shared_pools(db, user.name, user.rtp),
    )
    return render_template(
        'list_pools.html', user=user, user_pools=user_pools, shared_pools=shared_pools
    )


@app.route('/isos')
@auth.oidc_auth('default')
def isos():
    proxmox = connect_proxmox()
    stored_isos = get_isos(proxmox, app.config['PROXMOX_ISO_STORAGE'])
    return json.dumps({'isos': stored_isos})


@app.route('/hostname/<string:name>')
@auth.oidc_auth('default')
def hostname(name):
    proxmox = connect_proxmox()
    if not is_hostname_valid(name):
        return 'invalid'
    if not is_hostname_available(proxmox, name):
        return 'taken'
    return 'ok'


@app.route('/vm/<string:vmid>')
@auth.oidc_auth('default')
def vm_details(vmid):
    user = User(session['userinfo']['preferred_username'])
    connect_proxmox()
    if user.rtp or int(vmid) in user.allowed_vms:
        vm = VM(vmid)
        usage_check = user.check_usage(vm.cpu, vm.mem, 0)
        return render_template(
            'vm_details.html',
            user=user,
            vm=vm,
            usage=user.usage,
            limits=user.limits,
            usage_check=usage_check,
        )
    else:
        return abort(403)


@app.route('/vm/<string:vmid>/power/<string:action>', methods=['POST'])
@auth.oidc_auth('default')
def vm_power(vmid, action):
    user = User(session['userinfo']['preferred_username'])
    connect_proxmox()
    if user.rtp or int(vmid) in user.allowed_vms:
        vm = VM(vmid)
        vnc_token_key = f'vnc_token|{vmid}'
        # For deleting the token from redis later
        vnc_token = None
        try:
            vnc_token = redis_conn.get(vnc_token_key).decode('utf-8')
        except AttributeError as e:
            logging.warning(
                'Could not get vnc_token during %s: %s. Action is still being performed.',
                action,
                e,
            )
        if action == 'start':
            vmconfig = vm.config
            if app.config.get('ENABLE_VM_EXPIRATION'):
                expire_date = vm.expire
                if expire_date < datetime.date.today():
                    return 'expired', 400
            usage_check = user.check_usage(vmconfig['cores'], vmconfig['memory'], 0)
            if usage_check:
                return usage_check
            vm.start()
            _ensure_session_started(user)
        elif action == 'stop':
            vm.stop()
            if vnc_token is not None:
                delete_vnc_target(token=vnc_token)
                redis_conn.delete(vnc_token_key)
            _clear_session_if_idle(user)
        elif action == 'shutdown':
            vm.shutdown()
            if vnc_token is not None:
                delete_vnc_target(token=vnc_token)
                redis_conn.delete(vnc_token_key)
            _clear_session_if_idle(user)
        elif action == 'reset':
            vm.reset()
        elif action == 'suspend':
            vm.suspend()
            if vnc_token is not None:
                delete_vnc_target(token=vnc_token)
                redis_conn.delete(vnc_token_key)
            _clear_session_if_idle(user)
        elif action == 'resume':
            if app.config.get('ENABLE_VM_EXPIRATION'):
                expire_date = vm.expire
                if expire_date < datetime.date.today():
                    return 'expired', 400
            vm.resume()
            _ensure_session_started(user)
        return '', 200
    else:
        return '', 403


@app.route('/console/vm/<string:vmid>', methods=['POST'])
@auth.oidc_auth('default')
def vm_console(vmid):
    user = User(session['userinfo']['preferred_username'])
    proxmox = connect_proxmox()
    if user.rtp or int(vmid) in user.allowed_vms:
        # import pdb; pdb.set_trace()
        vm = VM(vmid)
        node_host = _node_fqdn(vm.node)
        proxmox = connect_proxmox(node_host)
        vnc_ticket, vnc_port = open_vnc_session(vmid, vm.node, proxmox)
        token = add_vnc_target(node_host, vnc_port)
        redis_conn.set(f'vnc_token|{vmid}', str(token))  # Store the VNC token in Redis.
        return {
            'host': app.config['VNC_HOST'],
            'port': app.config['VNC_PORT'],
            'token': token,
            'password': vnc_ticket,
        }, 200

    else:
        return '', 403


@app.route('/vm/<string:vmid>/cpu/<int:cores>', methods=['POST'])
@auth.oidc_auth('default')
def vm_cpu(vmid, cores):
    user = User(session['userinfo']['preferred_username'])
    connect_proxmox()
    if user.rtp or int(vmid) in user.allowed_vms:
        vm = VM(vmid)
        cur_cores = vm.cpu
        if cores >= cur_cores:
            if vm.qmpstatus in ('running', 'paused'):
                usage_check = user.check_usage(cores - cur_cores, 0, 0)
            else:
                usage_check = user.check_usage(cores, 0, 0)
            if usage_check:
                return usage_check
        vm.set_cpu(cores)
        return '', 200
    else:
        return '', 403


@app.route('/vm/<string:vmid>/mem/<int:mem>', methods=['POST'])
@auth.oidc_auth('default')
def vm_mem(vmid, mem):
    user = User(session['userinfo']['preferred_username'])
    connect_proxmox()
    if user.rtp or int(vmid) in user.allowed_vms:
        vm = VM(vmid)
        cur_mem = int(vm.mem) // 1024
        if mem >= cur_mem:
            if vm.qmpstatus in ('running', 'paused'):
                usage_check = user.check_usage(0, mem - cur_mem, 0)
            else:
                usage_check = user.check_usage(0, mem, 0)
            if usage_check:
                return usage_check
        vm.set_mem(mem * 1024)
        return '', 200
    else:
        return '', 403


@app.route('/vm/<string:vmid>/disk/create/<int:size>', methods=['POST'])
@auth.oidc_auth('default')
def create_disk(vmid, size):
    user = User(session['userinfo']['preferred_username'])
    connect_proxmox()
    if user.rtp or int(vmid) in user.allowed_vms:
        vm = VM(vmid)
        usage_check = user.check_usage(0, 0, size)
        if usage_check:
            return usage_check
        vm.create_disk(size)
        return '', 200
    else:
        return '', 403


@app.route('/vm/<string:vmid>/disk/<string:disk>/resize/<int:size>', methods=['POST'])
@auth.oidc_auth('default')
def resize_disk(vmid, disk, size):
    user = User(session['userinfo']['preferred_username'])
    connect_proxmox()
    if user.rtp or int(vmid) in user.allowed_vms:
        vm = VM(vmid)
        usage_check = user.check_usage(0, 0, size)
        if usage_check:
            return usage_check
        vm.resize_disk(disk, size)
        return '', 200
    else:
        return '', 403


@app.route('/vm/<string:vmid>/disk/<string:disk>/delete', methods=['POST'])
@auth.oidc_auth('default')
def delete_disk(vmid, disk):
    user = User(session['userinfo']['preferred_username'])
    connect_proxmox()
    if user.rtp or int(vmid) in user.allowed_vms:
        vm = VM(vmid)
        vm.delete_disk(disk)
        return '', 200
    else:
        return '', 403


@app.route('/vm/<string:vmid>/iso/create', methods=['POST'])
@auth.oidc_auth('default')
def iso_create(vmid):
    user = User(session['userinfo']['preferred_username'])
    connect_proxmox()
    if user.rtp or int(vmid) in user.allowed_vms:
        vm = VM(vmid)
        vm.add_iso_drive()
        return '', 200
    else:
        return '', 403


@app.route('/vm/<string:vmid>/iso/<string:iso_drive>/delete', methods=['POST'])
@auth.oidc_auth('default')
def iso_delete(vmid, iso_drive):
    user = User(session['userinfo']['preferred_username'])
    connect_proxmox()
    if user.rtp or int(vmid) in user.allowed_vms:
        vm = VM(vmid)
        vm.delete_iso_drive(iso_drive)
        return '', 200
    else:
        return '', 403


@app.route('/vm/<string:vmid>/iso/<string:iso_drive>/eject', methods=['POST'])
@auth.oidc_auth('default')
def iso_eject(vmid, iso_drive):
    user = User(session['userinfo']['preferred_username'])
    connect_proxmox()
    if user.rtp or int(vmid) in user.allowed_vms:
        vm = VM(vmid)
        vm.eject_iso(iso_drive)
        return '', 200
    else:
        return '', 403


@app.route('/vm/<string:vmid>/iso/<string:iso_drive>/mount/<string:iso>', methods=['POST'])
@auth.oidc_auth('default')
def iso_mount(vmid, iso_drive, iso):
    user = User(session['userinfo']['preferred_username'])
    connect_proxmox()
    if user.rtp or int(vmid) in user.allowed_vms:
        iso = '{}:iso/{}'.format(app.config['PROXMOX_ISO_STORAGE'], iso)
        vm = VM(vmid)
        vm.mount_iso(iso_drive, iso)
        return '', 200
    else:
        return '', 403


@app.route('/vm/<string:vmid>/net/create', methods=['POST'])
@auth.oidc_auth('default')
def create_net_interface(vmid):
    user = User(session['userinfo']['preferred_username'])
    connect_proxmox()
    if user.rtp or int(vmid) in user.allowed_vms:
        vm = VM(vmid)
        vnet, _ = ensure_student_network(db, app.config, user.name)
        vm.create_net('virtio', bridge=vnet)
        return '', 200
    else:
        return '', 403


@app.route('/vm/<string:vmid>/net/<string:netid>/delete', methods=['POST'])
@auth.oidc_auth('default')
def delete_net_interface(vmid, netid):
    user = User(session['userinfo']['preferred_username'])
    connect_proxmox()
    if user.rtp or int(vmid) in user.allowed_vms:
        vm = VM(vmid)
        vm.delete_net(netid)
        return '', 200
    else:
        return '', 403


@app.route('/vm/<string:vmid>/delete', methods=['POST'])
@auth.oidc_auth('default')
def delete(vmid):
    user = User(session['userinfo']['preferred_username'])
    connect_proxmox()
    if user.rtp or int(vmid) in user.allowed_vms:
        # send_stop_ssh_tunnel(vmid)
        # Submit the delete VM task to RQ
        q.enqueue(delete_vm_task, vmid)
        return '', 200
    else:
        return '', 403


@app.route('/vm/<string:vmid>/boot_order', methods=['POST'])
@auth.oidc_auth('default')
def set_boot_order(vmid):
    user = User(session['userinfo']['preferred_username'])
    connect_proxmox()
    if user.rtp or int(vmid) in user.allowed_vms:
        boot_order = []
        for key in sorted(request.form):
            boot_order.append(request.form[key])
        vm = VM(vmid)
        vm.set_boot_order(boot_order)
        return '', 200
    else:
        return '', 403


@app.route('/vm/create', methods=['GET', 'POST'])
@auth.oidc_auth('default')
def create():
    user = User(session['userinfo']['preferred_username'])
    proxmox = connect_proxmox()
    if user.active or user.rtp:
        if request.method == 'GET':
            stored_isos = get_isos(proxmox, app.config['PROXMOX_ISO_STORAGE'])
            pools = get_pools(proxmox, db)
            for pool in get_shared_pools(db, user.name, True):
                pools.append(pool.name)
            templates = get_templates(db)
            return render_template(
                'create_vm.html',
                user=user,
                usage=user.usage,
                limits=user.limits,
                percents=user.usage_percent,
                isos=stored_isos,
                pools=pools,
                templates=templates,
            )
        elif request.method == 'POST':
            name = request.form['name'].lower()
            cores = request.form['cores']
            memory = request.form['mem']
            template = request.form['template']
            disk = request.form['disk']
            iso = request.form['iso']
            ssh_key = request.form['ssh_key']
            if iso != 'none':
                iso = '{}:iso/{}'.format(app.config['PROXMOX_ISO_STORAGE'], iso)
            if not user.rtp:
                if template == 'none':
                    usage_check = user.check_usage(0, 0, disk)
                else:
                    usage_check = user.check_usage(cores, memory, disk)
                username = user.name
            else:
                usage_check = None
                username = request.form['user']
            if usage_check:
                return usage_check
            else:
                if is_hostname_valid(name) and is_hostname_available(proxmox, name):
                    if template == 'none':
                        q.enqueue(
                            create_vm_task,
                            username,
                            name,
                            cores,
                            memory,
                            disk,
                            iso,
                            job_timeout=300,
                        )
                    else:
                        q.enqueue(
                            setup_template_task,
                            template,
                            name,
                            username,
                            ssh_key,
                            cores,
                            memory,
                            job_timeout=600,
                        )
                        return '', 200
            return '', 200
        return None
    else:
        return '', 403


@app.route('/limits/<string:user>', methods=['POST'])
@auth.oidc_auth('default')
def set_limits(user):
    authuser = User(session['userinfo']['preferred_username'])
    if authuser.rtp:
        cpu = request.form['cpu']
        mem = request.form['mem']
        disk = request.form['disk']
        set_user_usage_limits(db, user, cpu, mem, disk)
        return '', 200
    else:
        return '', 403


@app.route('/user/<string:user>/delete', methods=['POST'])
@auth.oidc_auth('default')
def delete_user(user):
    authuser = User(session['userinfo']['preferred_username'])
    if authuser.rtp:
        connect_proxmox()
        User(user).delete()
        return '', 200
    else:
        return '', 403


@app.route('/settings')
@auth.oidc_auth('default')
def settings():
    user = User(session['userinfo']['preferred_username'])
    if user.rtp:
        templates = get_templates(db)
        db_ignored_pools = get_ignored_pools(db)
        db_allowed_users = get_allowed_users(db)
        return render_template(
            'settings.html',
            user=user,
            templates=templates,
            ignored_pools=db_ignored_pools,
            allowed_users=db_allowed_users,
        )
    else:
        return abort(403)


@app.route('/pool/<string:pool>/ignore', methods=['POST', 'DELETE'])
@auth.oidc_auth('default')
def ignored_pools(pool):
    user = User(session['userinfo']['preferred_username'])
    if user.rtp:
        if request.method == 'POST':
            add_ignored_pool(db, pool)
        elif request.method == 'DELETE':
            delete_ignored_pool(db, pool)
        return '', 200
    else:
        return '', 403


@app.route('/pool/shared/create', methods=['GET', 'POST'])
@auth.oidc_auth('default')
def create_shared_pool():
    user = User(session['userinfo']['preferred_username'])
    if request.method == 'GET':
        return render_template('create_pool.html', user=user)
    elif request.method == 'POST':
        name = request.form['name']
        members = request.form['members'].split(',')
        description = request.form['description']
        if user.rtp:
            try:
                proxmox = connect_proxmox()
                proxmox.pools.post(poolid=name, comment=description)
            except:
                return 'Error creating pool', 400
            add_shared_pool(db, name, members)
            return '', 200
        else:
            return '', 403


@app.route('/pool/shared/<string:name>/modify', methods=['POST'])
@auth.oidc_auth('default')
def modify_shared_pool(name):
    user = User(session['userinfo']['preferred_username'])
    members = request.form['members'].split(',')
    if user.rtp:
        pool = get_shared_pool(db, name)
        if pool:
            pool.members = members
            db.commit()
            return '', 200
        return 'Pool not found', 400
    else:
        return '', 403


@app.route('/pool/shared/<string:name>/delete', methods=['POST'])
@auth.oidc_auth('default')
def delete_shared_pool(name):
    user = User(session['userinfo']['preferred_username'])
    if user.rtp:
        pool = get_shared_pool(db, name)
        if pool:
            db.delete(pool)
            db.commit()
            proxmox = connect_proxmox()
            proxmox.pools(name).delete()
            return '', 200
        return 'Pool not found', 400
    else:
        return '', 403


@app.route('/user/<string:user>/allow', methods=['POST', 'DELETE'])
@auth.oidc_auth('default')
def allowed_users(user):
    authuser = User(session['userinfo']['preferred_username'])
    if authuser.rtp:
        if request.method == 'POST':
            add_allowed_user(db, user)
        elif request.method == 'DELETE':
            delete_allowed_user(db, user)
        return '', 200
    else:
        return '', 403


@app.route('/console/cleanup', methods=['POST'])
def cleanup_vnc():
    if request.form['token'] == app.config['VNC_CLEANUP_TOKEN']:
        logging.info('Cleaning up targets file...')
        with open(app.config['WEBSOCKIFY_TARGET_FILE'], 'w') as targets:
            targets.truncate()
        logging.info('Clearing vnc tokens from Redis...')
        count = 0
        ns_keys = 'vnc_token*'
        for key in redis_conn.scan_iter(ns_keys):
            redis_conn.delete(key)
            count += 1
        logging.info('Deleted %s key(s).', count)
        return '', 200
    logging.warning('Got bad cleanup request')
    return '', 403


@app.route('/template/<string:template_id>/disk')
@auth.oidc_auth('default')
def template_disk(template_id):
    if template_id == 'none':
        return '0'
    return get_template_disk(db, template_id)


@app.route('/template/<string:template_id>/edit', methods=['POST'])
@auth.oidc_auth('default')
def template_edit(template_id):
    user = User(session['userinfo']['preferred_username'])
    if user.rtp:
        name = request.form['name']
        disk = request.form['disk']
        set_template_info(db, template_id, name, disk)
        return '', 200
    else:
        return '', 403


@app.route('/logout')
@auth.oidc_logout
def logout():
    return redirect(url_for('list_vms'), 302)


@app.route('/health')
def health():
    """
    Shows an ok status if the application is up and running
    """
    return jsonify({'status': 'ok'})


@app.route('/session')
@auth.oidc_auth('default')
def session_info():
    user = User(session['userinfo']['preferred_username'])
    running_vms = _get_running_vms(user)
    session_start = get_session_start(redis_conn, user.name)
    if running_vms and session_start is None:
        session_start = set_session_start(redis_conn, user.name)
    if not running_vms and session_start is not None:
        clear_session(redis_conn, user.name)
        session_start = None

    timeout_seconds = int(app.config['SESSION_TIMEOUT_HOURS'] * 3600)
    remaining = None
    if session_start is not None:
        remaining = max(0, int(timeout_seconds - (time.time() - session_start)))

    return jsonify(
        {
            'running': bool(running_vms),
            'session_start': session_start,
            'timeout_seconds': timeout_seconds,
            'remaining_seconds': remaining,
            'running_vms': len(running_vms),
        }
    )


def exit_handler():
    stop_websockify()


atexit.register(exit_handler)

if __name__ == '__main__':
    app.run(threaded=False)

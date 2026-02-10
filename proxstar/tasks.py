import logging
import os
import time

import requests
from flask import Flask
from rq import get_current_job
from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from proxstar.db import (
    Base,
    get_vm_expire,
    delete_vm_expire,
    datetime,
    store_pool_cache,
    get_template,
    sync_templates,
)
from proxstar.proxmox import (
    connect_proxmox,
    get_pools,
    get_templates_from_pool,
    get_node_least_mem,
)
from proxstar.sdn import ensure_student_network
from proxstar.session import (
    clear_session,
    get_session_start,
    get_shutdown_started,
    set_session_start,
    set_shutdown_started,
)
from proxstar.user import User, get_vms_for_rtp
from proxstar.vm import VM, clone_vm, create_vm
from proxstar.util import sanitize_pool_name
from proxstar.vnc import delete_vnc_target

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.INFO)

app = Flask(__name__)
if os.path.exists(os.path.join(app.config.get('ROOT_DIR', os.getcwd()), 'config_local.py')):
    config = os.path.join(app.config.get('ROOT_DIR', os.getcwd()), 'config_local.py')
else:
    config = os.path.join(app.config.get('ROOT_DIR', os.getcwd()), 'config.py')
app.config.from_pyfile(config)


def connect_db():
    engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'])
    Base.metadata.bind = engine
    dbsession = sessionmaker(bind=engine)
    db = dbsession()
    return db


def set_job_status(job, status):
    job.meta['status'] = status
    job.save_meta()


def create_vm_task(user, name, cores, memory, disk, iso):  # pylint: disable=too-many-arguments
    with app.app_context():
        job = get_current_job()
        proxmox = connect_proxmox()
        db = connect_db()
        try:
            try:
                target_node = get_node_least_mem(proxmox)
                vnet, _ = ensure_student_network(db, app.config, user, proxmox)
            except Exception as e:  # pylint: disable=broad-except
                logging.error('[%s] SDN setup failed: %s', name, e)
                set_job_status(job, 'failed: sdn')
                raise
            pool_id = sanitize_pool_name(user)
            logging.info('[{}] Creating VM.'.format(name))
            set_job_status(job, 'creating VM')
            vmid = create_vm(
                proxmox, pool_id, name, cores, memory, disk, iso, vnet, node=target_node
            )
            logging.info('[{}] Waiting until Proxmox is done provisioning.'.format(name))
            set_job_status(job, 'waiting for Proxmox')
            timeout = 20
            retry = 0
            while retry < timeout:
                if not VM(vmid).is_provisioned():
                    retry += 1
                    time.sleep(3)
                    continue
                break
            if retry == timeout:
                logging.info('[{}] Failed to provision, deleting.'.format(name))
                set_job_status(job, 'failed to provision')
                delete_vm_task(vmid)
                return
            vm = VM(vmid)
            set_job_status(job, 'setting VM expiration')
            get_vm_expire(db, vmid, app.config['VM_EXPIRE_MONTHS'])
            logging.info('[{}] VM successfully provisioned.'.format(name))
            set_job_status(job, 'complete')
        finally:
            db.close()


def delete_vm_task(vmid):
    with app.app_context():
        db = connect_db()
        try:
            vm = VM(vmid)
            # do this before deleting the VM since it is hard to reconcile later
            if vm.status != 'stopped':
                vm.stop()
                retry = 0
                while retry < 10:
                    time.sleep(3)
                    if vm.status == 'stopped':
                        break
                    retry += 1
            vm.delete()
            delete_vm_expire(db, vmid)
        finally:
            db.close()


def process_expiring_vms_task():
    with app.app_context():
        if not app.config.get('ENABLE_VM_EXPIRATION'):
            return
        proxmox = connect_proxmox()
        db = connect_db()
        try:
            pools = get_pools(proxmox, db)
            for pool in pools:
                user = User(pool, db_session=db)
                vms = user.vms
                for vm in vms:
                    vm = VM(vm['vmid'])
                    days = (vm.expire - datetime.date.today()).days
                    if days <= -7:
                        logging.info(
                            'Deleting {} ({}) as it has been at least a week since expiration.'.format(
                                vm.name, vm.id
                            )
                        )
                        try:
                            redis_conn = Redis(app.config['REDIS_HOST'], app.config['REDIS_PORT'])
                            vmid = vm['vmid']
                            vnc_token_key = f'vnc_token|{vmid}'
                            vnc_token = redis_conn.get(vnc_token_key).decode('utf-8')
                            delete_vnc_target(token=vnc_token)
                            redis_conn.delete(vnc_token_key)
                        except Exception as e:  # pylint: disable=W0703
                            logging.error('Could not delete target from targets file: %s', e)

                        delete_vm_task(vm.id)
                    elif days <= 0:
                        vm.stop()
        finally:
            db.close()


def generate_pool_cache_task():
    with app.app_context():
        if not app.config.get('PROXMOX_HOSTS'):
            logging.info('No PROXMOX_HOSTS configured. Skipping pool cache generation.')
            return
        proxmox = connect_proxmox()
        db = connect_db()
        try:
            pools = get_vms_for_rtp(proxmox, db)
            store_pool_cache(db, pools)
        finally:
            db.close()


def setup_template_task(
    template_id, name, user, ssh_key, cores, memory
):  # pylint: disable=too-many-arguments
    with app.app_context():
        job = get_current_job()
        proxmox = connect_proxmox()
        db = connect_db()
        try:
            try:
                target_node = get_node_least_mem(proxmox)
                vnet, _ = ensure_student_network(db, app.config, user, proxmox)
            except Exception as e:  # pylint: disable=broad-except
                logging.error('[%s] SDN setup failed: %s', name, e)
                set_job_status(job, 'failed: sdn')
                raise
            pool_id = sanitize_pool_name(user)
            logging.info('[{}] Retrieving template info for template {}.'.format(name, template_id))
            get_template(db, template_id)
            logging.info('[{}] Cloning template {}.'.format(name, template_id))
            set_job_status(job, 'cloning template')
            vmid = clone_vm(
                proxmox,
                template_id,
                name,
                pool_id,
                full_clone=app.config.get('TEMPLATE_CLONE_FULL', True),
                target=target_node,
            )
            logging.info('[{}] Waiting until Proxmox is done provisioning.'.format(name))
            set_job_status(job, 'waiting for Proxmox')
            timeout = 25
            retry = 0
            while retry < timeout:
                if not VM(vmid).is_provisioned():
                    retry += 1
                    time.sleep(12)
                    continue
                break
            if retry == timeout:
                logging.info('[{}] Failed to provision, deleting.'.format(name))
                set_job_status(job, 'failed to provision')
                delete_vm_task(vmid)
                return

            vm = VM(vmid)
            vm.set_net_bridge('net0', vnet)
            get_vm_expire(db, vmid, app.config['VM_EXPIRE_MONTHS'])
            logging.info('[{}] Setting CPU and memory.'.format(name))
            set_job_status(job, 'setting CPU and memory')
            vm.set_cpu(cores)
            vm.set_mem(memory)
            logging.info('[{}] Applying cloud-init config.'.format(name))
            set_job_status(job, 'applying cloud-init')
            vm.set_ci_user(user)
            if ssh_key and ssh_key.strip():
                vm.set_ci_ssh_key(ssh_key)
            vm.set_ci_network()

            job.save_meta()
            logging.info('[{}] Starting VM.'.format(name))
            set_job_status(job, 'starting VM')
            job.save_meta()
            vm.start()
            logging.info('[{}] Template successfully provisioned.'.format(name))
            set_job_status(job, 'completed')
            job.save_meta()
        finally:
            db.close()


def sync_templates_task():
    with app.app_context():
        pool_name = app.config.get('TEMPLATE_POOL', '')
        if not pool_name:
            return
        proxmox = connect_proxmox()
        db = connect_db()
        try:
            templates = get_templates_from_pool(proxmox, pool_name)
            sync_templates(db, templates)
        finally:
            db.close()


def cleanup_vnc_task():
    """Removes all open VNC sessions. This runs in the RQ worker, and so
    needs to be routed properly via the Proxstar API
    TODO (willnilges): Use API, track the task IDs, and kill only the finished
    ones every couple of minutes
    https://github.com/ComputerScienceHouse/proxstar/issues/153
    """
    # FIXME (willnilges): This... might be working...?
    try:
        requests.post(
            '{}://{}/console/cleanup'.format(
                app.config.get('SERVER_SCHEME', 'http'), app.config['SERVER_NAME']
            ),
            data={'token': app.config['VNC_CLEANUP_TOKEN']},
            verify=False,
            timeout=30,
        )
    except Exception as e:  # pylint: disable=W0703
        logging.error('VNC cleanup request failed: %s', e)


def enforce_session_timeouts_task():
    with app.app_context():
        if not app.config.get('PROXMOX_HOSTS'):
            logging.info('No PROXMOX_HOSTS configured. Skipping session timeout enforcement.')
            return
        redis_conn = Redis(app.config['REDIS_HOST'], app.config['REDIS_PORT'])
        proxmox = connect_proxmox()
        db = connect_db()
        try:
            timeout_seconds = app.config['SESSION_TIMEOUT_HOURS'] * 3600
            grace_seconds = app.config['SESSION_SHUTDOWN_GRACE_MINUTES'] * 60

            for pool in get_pools(proxmox, db):
                user = User(pool, db_session=db)
                session_start = get_session_start(redis_conn, user.name)
                running_vms = []
                for vm in user.vms:
                    vm_obj = VM(vm['vmid'])
                    try:
                        if vm_obj.status in ('running', 'paused'):
                            running_vms.append(vm_obj)
                    except Exception:  # pylint: disable=broad-except
                        continue

                if not running_vms:
                    if session_start is not None:
                        clear_session(redis_conn, user.name)
                    continue

                if session_start is None:
                    set_session_start(redis_conn, user.name)
                    continue

                now = time.time()
                if now - session_start < timeout_seconds:
                    continue

                shutdown_started = get_shutdown_started(redis_conn, user.name)
                if shutdown_started is None:
                    set_shutdown_started(redis_conn, user.name)
                    for vm in running_vms:
                        try:
                            vm.shutdown()
                        except Exception:  # pylint: disable=broad-except
                            pass
                    continue

                if now - shutdown_started >= grace_seconds:
                    for vm in running_vms:
                        try:
                            vm.stop()
                        except Exception:  # pylint: disable=broad-except
                            pass
        finally:
            db.close()

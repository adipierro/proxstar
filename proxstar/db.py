import datetime
import os

from flask import current_app as app, has_app_context

from dateutil.relativedelta import relativedelta
from sqlalchemy import exists

from proxstar.ldapdb import is_rtp

# pylint: disable=unused-import
from proxstar.models import (
    Base,
    Allowed_Users,
    Ignored_Pools,
    Pool_Cache,
    Template,
    Usage_Limit,
    VM_Expiration,
    Shared_Pools,
    Student_Network,
)


def _get_default_limits():
    if has_app_context():
        return (
            app.config.get('DEFAULT_CPU_LIMIT', 8),
            app.config.get('DEFAULT_MEM_LIMIT', 8),
            app.config.get('DEFAULT_DISK_LIMIT', 250),
        )
    return (
        int(os.environ.get('PROXSTAR_DEFAULT_CPU_LIMIT', '8')),
        int(os.environ.get('PROXSTAR_DEFAULT_MEM_LIMIT', '8')),
        int(os.environ.get('PROXSTAR_DEFAULT_DISK_LIMIT', '250')),
    )


def get_vm_expire(db, vmid, months):
    if db.query(exists().where(VM_Expiration.id == vmid)).scalar():
        expire = db.query(VM_Expiration).filter(VM_Expiration.id == vmid).one().expire_date
    else:
        expire = datetime.date.today() + relativedelta(months=months)
        new_expire = VM_Expiration(id=vmid, expire_date=expire)
        db.add(new_expire)
        db.commit()
    return expire


def renew_vm_expire(db, vmid, months):
    if db.query(exists().where(VM_Expiration.id == vmid)).scalar():
        expire = db.query(VM_Expiration).filter(VM_Expiration.id == vmid).one()
        new_expire = datetime.date.today() + relativedelta(months=months)
        expire.expire_date = new_expire
        db.commit()
    else:
        expire = datetime.date.today() + relativedelta(months=months)
        new_expire = VM_Expiration(id=vmid, expire_date=expire)
        db.add(new_expire)
        db.commit()


def delete_vm_expire(db, vmid):
    if db.query(exists().where(VM_Expiration.id == vmid)).scalar():
        expire = db.query(VM_Expiration).filter(VM_Expiration.id == vmid).one()
        db.delete(expire)
        db.commit()


def get_expiring_vms(db):
    expiring = []
    today = datetime.date.today()
    expire = db.query(VM_Expiration).filter((VM_Expiration.expire_date - today) <= 10).all()
    for vm in expire:
        expiring.append(vm.id)
    return expiring


def get_user_usage_limits(db, user):
    limits = {}
    if is_rtp(user):
        limits['cpu'] = 1000
        limits['mem'] = 1000
        limits['disk'] = 100000
    elif db.query(exists().where(Usage_Limit.id == user)).scalar():
        limits['cpu'] = db.query(Usage_Limit).filter(Usage_Limit.id == user).one().cpu
        limits['mem'] = db.query(Usage_Limit).filter(Usage_Limit.id == user).one().mem
        limits['disk'] = db.query(Usage_Limit).filter(Usage_Limit.id == user).one().disk
    else:
        default_cpu, default_mem, default_disk = _get_default_limits()
        limits['cpu'] = default_cpu
        limits['mem'] = default_mem
        limits['disk'] = default_disk
    return limits


def set_user_usage_limits(db, user, cpu, mem, disk):
    if db.query(exists().where(Usage_Limit.id == user)).scalar():
        limits = db.query(Usage_Limit).filter(Usage_Limit.id == user).one()
        limits.cpu = cpu
        limits.mem = mem
        limits.disk = disk
        db.commit()
    else:
        limits = Usage_Limit(id=user, cpu=cpu, mem=mem, disk=disk)
        db.add(limits)
        db.commit()


def delete_user_usage_limits(db, user):
    if db.query(exists().where(Usage_Limit.id == user)).scalar():
        limits = db.query(Usage_Limit).filter(Usage_Limit.id == user).one()
        db.delete(limits)
        db.commit()


def store_pool_cache(db, pools):
    db.query(Pool_Cache).delete()
    for pool in pools:
        pool_entry = Pool_Cache(
            pool=pool['user'],
            vms=pool['vms'],
            num_vms=pool['num_vms'],
            usage=pool['usage'],
            limits=pool['limits'],
            percents=pool['percents'],
        )
        db.add(pool_entry)
    db.commit()


def get_pool_cache(db):
    db_pools = db.query(Pool_Cache).all()
    pools = []
    for pool in db_pools:
        pool_dict = {}
        pool_dict['user'] = pool.pool
        pool_dict['vms'] = pool.vms
        pool_dict['num_vms'] = pool.num_vms
        pool_dict['usage'] = pool.usage
        pool_dict['limits'] = pool.limits
        pool_dict['percents'] = pool.percents
        pools.append(pool_dict)
    pools = sorted(pools, key=lambda x: x['user'])
    return pools


def get_ignored_pools(db):
    ignored_pools = []
    for pool in db.query(Ignored_Pools).all():
        ignored_pools.append(pool.id)
    return ignored_pools


def delete_ignored_pool(db, pool):
    if db.query(exists().where(Ignored_Pools.id == pool)).scalar():
        ignored_pool = db.query(Ignored_Pools).filter(Ignored_Pools.id == pool).one()
        db.delete(ignored_pool)
        db.commit()


def add_ignored_pool(db, pool):
    if not db.query(exists().where(Ignored_Pools.id == pool)).scalar():
        ignored_pool = Ignored_Pools(id=pool)
        db.add(ignored_pool)
        db.commit()


def get_templates(db):
    templates = []
    for template in db.query(Template).all():
        template_dict = {}
        template_dict['id'] = template.id
        template_dict['name'] = template.name
        template_dict['disk'] = template.disk
        templates.append(template_dict)
    return templates


def get_template(db, template_id):
    template_dict = {}
    if db.query(exists().where(Template.id == template_id)).scalar():
        template = db.query(Template).filter(Template.id == template_id).one()
        template_dict['id'] = template.id
        template_dict['name'] = template.name
        template_dict['disk'] = template.disk
    return template_dict


def get_template_disk(db, template_id):
    disk = 0
    if db.query(exists().where(Template.id == template_id)).scalar():
        template = db.query(Template).filter(Template.id == template_id).one()
        disk = template.disk
    return str(disk)


def get_allowed_users(db):
    allowed_users = []
    for user in db.query(Allowed_Users).all():
        allowed_users.append(user.id)
    return allowed_users


def add_allowed_user(db, user):
    if not db.query(exists().where(Allowed_Users.id == user)).scalar():
        allowed_user = Allowed_Users(id=user)
        db.add(allowed_user)
        db.commit()


def delete_allowed_user(db, user):
    if db.query(exists().where(Allowed_Users.id == user)).scalar():
        allowed_user = db.query(Allowed_Users).filter(Allowed_Users.id == user).one()
        db.delete(allowed_user)
        db.commit()


def set_template_info(db, template_id, name, disk):
    if db.query(
        exists().where(
            Template.id == template_id,
        )
    ).scalar():
        template = (
            db.query(Template)
            .filter(
                Template.id == template_id,
            )
            .one()
        )
        template.name = name
        template.disk = disk
        db.commit()


def sync_templates(db, templates):
    if templates is None:
        return
    template_ids = set()
    for template in templates:
        template_id = int(template['id'])
        template_ids.add(template_id)
        record = db.query(Template).filter(Template.id == template_id).one_or_none()
        disk = template.get('disk')
        if record:
            record.name = template.get('name', record.name)
            if disk is not None and (record.disk == 0 or record.disk is None):
                record.disk = disk
        else:
            db.add(
                Template(
                    id=template_id,
                    name=template.get('name', str(template_id)),
                    disk=disk or 0,
                )
            )
    if template_ids:
        db.query(Template).filter(~Template.id.in_(template_ids)).delete(
            synchronize_session=False
        )
    else:
        db.query(Template).delete()
    db.commit()


def add_shared_pool(db, name, members):
    if db.query(Shared_Pools).get(name):
        return 'Name Already in Use'
    db.add(Shared_Pools(name=name, members=members))
    db.commit()


def get_shared_pool(db, name):
    return db.query(Shared_Pools).get(name)


def get_shared_pools(db, user, all_pools):
    if all_pools:
        return db.query(Shared_Pools).all()
    pools = []
    for pool in db.query(Shared_Pools).filter(Shared_Pools.members.contains(f'{{{user}}}')).all():
        pools.append(pool)
    return pools


def get_student_network(db, user):
    return db.query(Student_Network).filter(Student_Network.username == user).one_or_none()


def add_student_network(db, user, vnet, subnet):
    entry = Student_Network(username=user, vnet=vnet, subnet=subnet)
    db.add(entry)
    db.commit()
    return entry


def get_assigned_student_subnets(db):
    return [entry.subnet for entry in db.query(Student_Network).all()]

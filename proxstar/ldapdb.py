from flask import current_app as app, has_request_context, session


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


def _get_groups():
    if not has_request_context():
        return []
    info = session.get('userinfo', {})
    claim = app.config.get('OIDC_GROUPS_CLAIM', 'groups')
    raw = _get_claim(info, claim)
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        return [raw]
    return []


def _has_any_group(target_groups):
    if not target_groups:
        return False
    groups = set(_get_groups())
    return any(group in groups for group in target_groups)


def is_rtp(user):
    return _has_any_group(app.config.get('OIDC_ADMIN_GROUPS', []))


def is_active(user):
    active_groups = app.config.get('OIDC_ACTIVE_GROUPS', [])
    student_groups = app.config.get('OIDC_STUDENT_GROUPS', [])
    if not active_groups and not student_groups:
        return True
    return _has_any_group(active_groups) or _has_any_group(student_groups)


def is_current_student(user):
    return _has_any_group(app.config.get('OIDC_STUDENT_GROUPS', []))


def is_user(user):
    return bool(user)

import time


SESSION_KEY_PREFIX = 'session_start|'
SESSION_SHUTDOWN_PREFIX = 'session_shutdown|'


def get_session_key(user):
    return f'{SESSION_KEY_PREFIX}{user}'


def get_shutdown_key(user):
    return f'{SESSION_SHUTDOWN_PREFIX}{user}'


def get_session_start(redis_conn, user):
    value = redis_conn.get(get_session_key(user))
    if value is None:
        return None
    return float(value)


def set_session_start(redis_conn, user, start_ts=None):
    if start_ts is None:
        start_ts = time.time()
    redis_conn.set(get_session_key(user), str(start_ts))
    return start_ts


def clear_session(redis_conn, user):
    redis_conn.delete(get_session_key(user))
    redis_conn.delete(get_shutdown_key(user))


def get_shutdown_started(redis_conn, user):
    value = redis_conn.get(get_shutdown_key(user))
    if value is None:
        return None
    return float(value)


def set_shutdown_started(redis_conn, user, ts=None):
    if ts is None:
        ts = time.time()
    redis_conn.set(get_shutdown_key(user), str(ts))
    return ts

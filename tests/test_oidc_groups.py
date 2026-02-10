from flask import session

from proxstar import app
from proxstar import ldapdb


def test_is_active_defaults_true_when_no_groups_configured():
    app.config['OIDC_ACTIVE_GROUPS'] = []
    app.config['OIDC_STUDENT_GROUPS'] = []
    with app.test_request_context():
        session['userinfo'] = {'preferred_username': 'alice'}
        assert ldapdb.is_active('alice') is True


def test_group_claim_path_supports_nested_claims():
    app.config['OIDC_GROUPS_CLAIM'] = 'realm_access.roles'
    app.config['OIDC_ADMIN_GROUPS'] = ['admins']
    with app.test_request_context():
        session['userinfo'] = {
            'preferred_username': 'alice',
            'realm_access': {'roles': ['admins', 'users']},
        }
        assert ldapdb.is_rtp('alice') is True

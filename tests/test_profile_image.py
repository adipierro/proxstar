from flask import session

from proxstar import app, _profile_image_url


def test_profile_image_uses_oidc_claim_for_current_user():
    app.config['OIDC_PROFILE_IMAGE_CLAIM'] = 'picture'
    with app.test_request_context():
        session['userinfo'] = {
            'preferred_username': 'alice',
            'picture': 'https://img.example.com/alice.png',
        }
        assert _profile_image_url() == 'https://img.example.com/alice.png'


def test_profile_image_fallback_base_url_for_other_user():
    app.config['PROFILE_IMAGE_URL_BASE'] = 'https://profiles.example.com'
    with app.test_request_context():
        session['userinfo'] = {'preferred_username': 'alice'}
        assert (
            _profile_image_url('bob') == 'https://profiles.example.com/bob'
        )

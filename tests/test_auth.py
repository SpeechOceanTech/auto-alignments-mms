from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from alignment_web.auth import AuthStore, require_account, router


def make_client(tmp_path):
    sent = {}
    store = AuthStore(tmp_path / 'auth.db', b'x' * 32, lambda email, code: sent.update({email: code}))
    app = FastAPI()
    app.state.auth_store = store
    app.include_router(router)

    @app.post('/private')
    def private(user=Depends(require_account)):
        return user

    return TestClient(app), sent, store


def login(client, sent, email):
    assert client.post('/api/auth/request-code', json={'email': email}).status_code == 200
    response = client.post('/api/auth/verify-code', json={'email': email, 'code': sent[email]})
    assert response.status_code == 200
    return response.json()


def test_email_verification_cookie_csrf_and_logout(tmp_path):
    client, sent, store = make_client(tmp_path)
    assert client.get('/api/auth/me').status_code == 401
    client.post('/api/auth/request-code', json={'email': 'not@example.com'})
    assert not sent
    data = login(client, sent, 'alice@dataoceanai.com')
    assert data['user']['email_verified']
    assert 'HttpOnly' in client.cookies.jar._cookies['testserver.local']['/']['alignment_session']._rest
    assert client.post('/api/auth/verify-code', json={'email': 'alice@dataoceanai.com', 'code': sent['alice@dataoceanai.com']}).status_code == 400
    assert client.post('/private').status_code == 403
    assert client.post('/private', headers={'x-csrf-token': data['csrf_token']}).status_code == 200
    assert client.post('/private', headers={'x-csrf-token': data['csrf_token'], 'origin': 'http://evil.example'}).status_code == 403
    assert client.post('/api/auth/logout', headers={'x-csrf-token': data['csrf_token']}).status_code == 200
    assert client.get('/api/auth/me').status_code == 401


def test_username_prefix_and_duhu_admin(tmp_path):
    client, sent, store = make_client(tmp_path)
    assert client.post('/api/auth/request-code', json={'email': 'DuHu'}).status_code == 200
    response = client.post('/api/auth/verify-code', json={'email': 'duhu', 'code': sent['duhu@dataoceanai.com']})
    assert response.status_code == 200
    assert response.json()['user']['username'] == 'duhu'
    assert response.json()['user']['is_admin'] is True


def test_admin_permissions_and_disable_revoke_session(tmp_path):
    admin, sent, store = make_client(tmp_path)
    person = TestClient(admin.app)
    person_session = login(person, sent, 'person@dataoceanai.com')
    person_id = person_session['user']['id']
    assert person.get('/api/admin/users').status_code == 403
    admin_session = login(admin, sent, 'duhu@dataoceanai.com')
    headers = {'x-csrf-token': admin_session['csrf_token']}
    assert len(admin.get('/api/admin/users').json()['users']) == 2
    assert admin.patch('/api/admin/users/' + admin_session['user']['id'], json={'is_admin': False}, headers=headers).status_code == 400
    assert admin.patch('/api/admin/users/' + person_id, json={'is_active': False}, headers=headers).status_code == 200
    assert person.get('/api/auth/me').status_code == 401
    assert admin.patch('/api/admin/users/' + person_id, json={'is_active': True}, headers=headers).status_code == 200
    assert person.get('/api/auth/me').status_code == 401


def test_expired_code_and_rate_limit(tmp_path):
    clock = [1000.0]
    sent = []
    store = AuthStore(tmp_path / 'auth.db', b'x' * 32, lambda email, code: sent.append(code), clock=lambda: clock[0])
    for _ in range(6):
        store.request_code('alice@dataoceanai.com', 'client')
    assert len(sent) == 5
    clock[0] += 601
    assert store.verify_code('alice@dataoceanai.com', sent[-1], 'client') is None


def test_api_key_owner_access_revocation_and_no_account_management(tmp_path):
    admin, sent, store = make_client(tmp_path)
    session = login(admin, sent, 'duhu@dataoceanai.com')
    csrf = {'x-csrf-token': session['csrf_token']}
    assert admin.post('/api/auth/api-keys', json={'name': 'script'}).status_code == 403
    created = admin.post('/api/auth/api-keys', json={'name': 'script'}, headers=csrf)
    assert created.status_code == 200
    key, token = created.json()['key'], created.json()['token']
    assert created.headers['cache-control'] == 'no-store'
    assert token.startswith('align_')
    stored = store.list_api_keys(session['user']['id'])
    assert stored[0]['id'] == key['id'] and 'token' not in stored[0]
    with store.connect() as db:
        assert token not in tuple(db.execute('SELECT * FROM api_keys').fetchone())
    bearer = {'Authorization': 'Bearer ' + token}
    # A bearer credential remains restricted even if an administrator cookie is present.
    assert admin.post('/private', headers=bearer).json()['id'] == session['user']['id']
    assert admin.get('/api/admin/users', headers=bearer).status_code == 403
    assert admin.get('/api/auth/api-keys', headers=bearer).status_code == 403
    assert admin.post('/api/auth/api-keys', json={'name': 'new'}, headers=bearer).status_code == 403
    assert admin.get('/api/auth/me', headers=bearer).status_code == 403

    other = TestClient(admin.app)
    other_session = login(other, sent, 'other@dataoceanai.com')
    assert other.delete('/api/auth/api-keys/' + key['id'], headers={'x-csrf-token': other_session['csrf_token']}).status_code == 404
    assert admin.delete('/api/auth/api-keys/' + key['id'], headers=csrf).status_code == 200
    assert admin.post('/private', headers=bearer).status_code == 401


def test_api_key_stops_working_when_user_is_disabled(tmp_path):
    admin, sent, store = make_client(tmp_path)
    person = TestClient(admin.app)
    person_session = login(person, sent, 'person@dataoceanai.com')
    result = person.post('/api/auth/api-keys', json={'name': 'task runner'},
                         headers={'x-csrf-token': person_session['csrf_token']}).json()
    bearer = {'Authorization': 'Bearer ' + result['token']}
    assert person.post('/private', headers=bearer).status_code == 200
    admin_session = login(admin, sent, 'duhu@dataoceanai.com')
    assert admin.patch('/api/admin/users/' + person_session['user']['id'], json={'is_active': False},
                       headers={'x-csrf-token': admin_session['csrf_token']}).status_code == 200
    assert person.post('/private', headers=bearer).status_code == 401

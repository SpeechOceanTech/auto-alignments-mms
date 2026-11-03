"""Email verification, browser sessions and administrator account management."""
import hashlib
import hmac
import logging
import re
import secrets
import smtplib
import sqlite3
import ssl
import time
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response

COOKIE_NAME = 'alignment_session'
SESSION_SECONDS = 14 * 24 * 60 * 60
CODE_SECONDS = 10 * 60
EMAIL_PATTERN = re.compile(r'^[a-z0-9][a-z0-9._+-]{0,63}@dataoceanai\.com$')
router = APIRouter(prefix='/api')


def normalize_email(value):
    value = str(value or '').strip().lower()
    if not EMAIL_PATTERN.fullmatch(value) or '..' in value or value.split('@')[0].endswith('.'):
        return None
    return value


class SmtpCodeSender:
    def __init__(self, host, port, username, password, sender):
        self.host, self.port, self.username, self.password, self.sender = host, port, username, password, sender

    def __call__(self, email, code):
        message = EmailMessage()
        message['From'], message['To'] = self.sender, email
        message['Subject'] = 'Audio Alignment verification code'
        message.set_content(f'Your verification code is {code}. It expires in 10 minutes.')
        with smtplib.SMTP_SSL(self.host, self.port, context=ssl.create_default_context(), timeout=20) as smtp:
            smtp.login(self.username, self.password)
            smtp.send_message(message)


class AuthStore:
    def __init__(self, db_path, secret, sender, admin_email='duhu@dataoceanai.com', clock=time.time):
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError('A persistent secret of at least 32 bytes is required')
        self.db_path, self.secret, self.sender, self.clock = str(db_path), secret, sender, clock
        self.admin_email = normalize_email(admin_email)
        if not self.admin_email:
            raise ValueError('Invalid administrator email')
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
                    is_admin INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS codes (
                    email TEXT PRIMARY KEY, digest TEXT NOT NULL, expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    name TEXT NOT NULL, digest TEXT NOT NULL UNIQUE,
                    created_at REAL NOT NULL, last_used_at REAL
                );
                CREATE INDEX IF NOT EXISTS api_keys_user ON api_keys(user_id);
                CREATE TABLE IF NOT EXISTS rate_events (scope TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS auth_rate_scope ON rate_events(scope, created_at);
            ''')

    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def digest(self, purpose, value):
        return hmac.new(self.secret, (purpose + '\0' + value).encode(), hashlib.sha256).hexdigest()

    def _allowed(self, db, action, email, client):
        now = self.clock()
        db.execute('DELETE FROM rate_events WHERE created_at <= ?', (now - 900,))
        scopes = [(f'{action}:email:{email}', 5 if action == 'request' else 10),
                  (f'{action}:client:{client[:200]}', 30 if action == 'request' else 100)]
        if any(db.execute('SELECT COUNT(*) FROM rate_events WHERE scope=?', (scope,)).fetchone()[0] >= limit
               for scope, limit in scopes):
            return False
        db.executemany('INSERT INTO rate_events VALUES (?,?)', [(scope, now) for scope, _ in scopes])
        return True

    def request_code(self, email, client):
        normalized = normalize_email(email)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not self._allowed(db, 'request', normalized or 'invalid', client) or not normalized:
                return
            code = f'{secrets.randbelow(100_000_000):08d}'
            digest = self.digest('code', normalized + '\0' + code)
            db.execute('INSERT OR REPLACE INTO codes VALUES (?,?,?)', (normalized, digest, self.clock() + CODE_SECONDS))
        self.sender(normalized, code)

    def verify_code(self, email, code, client):
        normalized = normalize_email(email)
        token = secrets.token_urlsafe(32)
        user = None
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            allowed = self._allowed(db, 'verify', normalized or 'invalid', client)
            row = db.execute('SELECT * FROM codes WHERE email=?', (normalized,)).fetchone() if normalized else None
            supplied = self.digest('code', str(normalized) + '\0' + str(code or '')[:256])
            if allowed and row and row['expires_at'] > self.clock() and hmac.compare_digest(row['digest'], supplied):
                db.execute('DELETE FROM codes WHERE email=?', (normalized,))
                user = db.execute('SELECT * FROM users WHERE email=?', (normalized,)).fetchone()
                if user is None:
                    user_id = 'usr_' + secrets.token_hex(16)
                    db.execute('INSERT INTO users VALUES (?,?,?,?,?,?)',
                               (user_id, normalized.split('@')[0], normalized, int(normalized == self.admin_email), 1, self.clock()))
                    user = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
                if user['is_active']:
                    db.execute('INSERT INTO sessions VALUES (?,?,?)',
                               (self.digest('session', token), user['id'], self.clock() + SESSION_SECONDS))
                else:
                    user = None
        if user is None:
            return None
        return {'token': token, 'user': self._public(user), 'csrf_token': self.digest('csrf', token)}

    @staticmethod
    def _public(row):
        return {'id': row['id'], 'user_id': row['id'], 'username': row['username'], 'email': row['email'],
                'is_admin': bool(row['is_admin']), 'is_active': bool(row['is_active']),
                'email_verified': True, 'created_at': row['created_at']}

    def authenticate(self, token):
        if not token:
            return None
        with self.connect() as db:
            row = db.execute('''SELECT u.* FROM users u JOIN sessions s ON u.id=s.user_id
                WHERE s.digest=? AND s.expires_at>? AND u.is_active=1''',
                (self.digest('session', token), self.clock())).fetchone()
        return self._public(row) if row else None

    def check_csrf(self, token, csrf):
        return bool(token and hmac.compare_digest(self.digest('csrf', token).encode(), str(csrf or '').encode()))

    def create_api_key(self, user_id, name):
        name = str(name or '').strip()
        if not name or len(name) > 100:
            raise ValueError('密钥名称长度必须为 1 到 100 个字符')
        key_id = 'key_' + secrets.token_hex(16)
        token = 'align_' + secrets.token_urlsafe(32)
        created_at = self.clock()
        with self.connect() as db:
            db.execute('INSERT INTO api_keys VALUES (?,?,?,?,?,NULL)',
                       (key_id, user_id, name, self.digest('api_key', token), created_at))
        return {'key': {'id': key_id, 'name': name, 'created_at': created_at, 'last_used_at': None},
                'token': token}

    def list_api_keys(self, user_id):
        with self.connect() as db:
            rows = db.execute('SELECT id,name,created_at,last_used_at FROM api_keys WHERE user_id=? ORDER BY created_at DESC',
                              (user_id,)).fetchall()
        return [dict(row) for row in rows]

    def revoke_api_key(self, user_id, key_id):
        with self.connect() as db:
            return db.execute('DELETE FROM api_keys WHERE id=? AND user_id=?', (key_id, user_id)).rowcount == 1

    def authenticate_api_key(self, token):
        if not token or not token.startswith('align_'):
            return None
        with self.connect() as db:
            digest = self.digest('api_key', token)
            row = db.execute('''SELECT u.* FROM users u JOIN api_keys k ON u.id=k.user_id
                WHERE k.digest=? AND u.is_active=1''', (digest,)).fetchone()
            if row is not None:
                db.execute('UPDATE api_keys SET last_used_at=? WHERE digest=?', (self.clock(), digest))
        return self._public(row) if row else None

    def logout(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE digest=?', (self.digest('session', token),))

    def list_users(self):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM users ORDER BY created_at DESC').fetchall()
        return [self._public(row) for row in rows]

    def update_user(self, user_id, actor_id, changes):
        fields = {key: value for key, value in changes.items() if key in ('is_admin', 'is_active')}
        if not fields or any(not isinstance(v, bool) for v in fields.values()):
            raise ValueError('请提供有效的账号状态或管理员权限')
        if user_id == actor_id and (fields.get('is_admin') is False or fields.get('is_active') is False):
            raise ValueError('不能停用或降级当前账号')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
            if row is None:
                return None
            db.execute('UPDATE users SET is_admin=?, is_active=? WHERE id=?',
                       (int(fields.get('is_admin', bool(row['is_admin']))),
                        int(fields.get('is_active', bool(row['is_active']))), user_id))
            if fields.get('is_active') is False:
                db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
            return self._public(db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone())


def _same_origin(request):
    origin = request.headers.get('origin')
    if not origin:
        return
    parsed = urlsplit(origin)
    if parsed.scheme not in ('http', 'https') or parsed.netloc.lower() != request.headers.get('host', '').lower() or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise HTTPException(403, '无效的请求来源')


def require_account(request: Request):
    store = request.app.state.auth_store
    if store is None:
        raise HTTPException(503, '账户服务未配置')
    authorization = request.headers.get('authorization', '')
    if authorization:
        scheme, _, token = authorization.partition(' ')
        if scheme.lower() != 'bearer' or not token:
            raise HTTPException(401, '无效的 API 密钥')
        user = store.authenticate_api_key(token.strip())
        request.state.auth_kind = 'api_key'
    else:
        token = request.cookies.get(COOKIE_NAME, '')
        user = store.authenticate(token)
        request.state.auth_kind = 'session'
    if not user:
        raise HTTPException(401, '请先登录')
    if request.state.auth_kind == 'session' and request.method not in ('GET', 'HEAD', 'OPTIONS'):
        _same_origin(request)
        if not store.check_csrf(token, request.headers.get('x-csrf-token')):
            raise HTTPException(403, '无效的 CSRF 验证')
    return user


def require_session(request: Request, user: dict = Depends(require_account)):
    if request.state.auth_kind != 'session':
        raise HTTPException(403, '此操作需要网页账号登录')
    return user


def require_admin(user: dict = Depends(require_session)):
    if not user['is_admin']:
        raise HTTPException(403, '需要管理员权限')
    return user


def _client(request):
    return request.client.host if request.client else 'unknown'


@router.post('/auth/request-code')
def request_code(request: Request, payload: dict):
    _same_origin(request)
    if request.app.state.auth_store is None:
        raise HTTPException(503, '账户服务未配置')
    try:
        request.app.state.auth_store.request_code(payload.get('email'), _client(request))
    except Exception:
        logging.getLogger(__name__).warning('Verification request could not be delivered')
        raise HTTPException(503, '验证码发送失败，请联系管理员')
    return {'message': '如果邮箱符合条件，验证码将发送到邮箱。'}


@router.post('/auth/verify-code')
def verify_code(request: Request, response: Response, payload: dict):
    _same_origin(request)
    store = request.app.state.auth_store
    if store is None:
        raise HTTPException(503, '账户服务未配置')
    result = store.verify_code(payload.get('email'), payload.get('code'), _client(request))
    if not result:
        raise HTTPException(400, '验证码无效或已过期')
    response.set_cookie(COOKIE_NAME, result['token'], httponly=True,
                        secure=getattr(request.app.state, 'auth_secure_cookie', False),
                        samesite='strict', max_age=SESSION_SECONDS, path='/')
    response.headers['Cache-Control'] = 'no-store'
    return {'user': result['user'], 'csrf_token': result['csrf_token']}


@router.get('/auth/me')
def me(request: Request, response: Response, user: dict = Depends(require_session)):
    response.headers['Cache-Control'] = 'no-store'
    return {'user': user, 'csrf_token': request.app.state.auth_store.digest('csrf', request.cookies[COOKIE_NAME])}


@router.post('/auth/logout')
def logout(request: Request, response: Response, user: dict = Depends(require_session)):
    request.app.state.auth_store.logout(request.cookies[COOKIE_NAME])
    response.delete_cookie(COOKIE_NAME, path='/', httponly=True, samesite='strict',
                           secure=getattr(request.app.state, 'auth_secure_cookie', False))
    return {'ok': True}


@router.get('/admin/users')
def list_users(request: Request, user: dict = Depends(require_admin)):
    return {'users': request.app.state.auth_store.list_users()}


@router.patch('/admin/users/{user_id}')
def update_user(user_id: str, request: Request, payload: dict, user: dict = Depends(require_admin)):
    try:
        updated = request.app.state.auth_store.update_user(user_id, user['id'], payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if updated is None:
        raise HTTPException(404, '账号不存在')
    return {'user': updated}


@router.get('/auth/api-keys')
def list_api_keys(request: Request, user: dict = Depends(require_session)):
    return {'keys': request.app.state.auth_store.list_api_keys(user['id'])}


@router.post('/auth/api-keys')
def create_api_key(request: Request, response: Response, payload: dict, user: dict = Depends(require_session)):
    try:
        result = request.app.state.auth_store.create_api_key(user['id'], payload.get('name'))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    response.headers['Cache-Control'] = 'no-store'
    return result


@router.delete('/auth/api-keys/{key_id}')
def revoke_api_key(key_id: str, request: Request, user: dict = Depends(require_session)):
    if not request.app.state.auth_store.revoke_api_key(user['id'], key_id):
        raise HTTPException(404, '密钥不存在')
    return {'ok': True}

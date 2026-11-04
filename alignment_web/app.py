"""Single-process HTTP service for authenticated alignment jobs."""
import logging
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import uuid
import unicodedata
import wave
import zipfile
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from pydantic import BaseModel, Field

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from alignment_languages import COMMON_LANGUAGES, canonical_locale, normalize_language
from alignment_csv import audition_csv_bytes, read_alignment_csv

from .store import JobStore
from .statistics import audio_duration, output_sentences
from .language_check import router as language_check_router
from .auth import AuthStore, SmtpCodeSender, require_account, require_admin, router as auth_router

LOG = logging.getLogger(__name__)
TEXT_LIMIT = 2 * 1024 * 1024
FORM_OVERHEAD = 1024 * 1024
JOB_PATTERN = re.compile(r'^[0-9a-f]{32}$')
AUDIO_EXTENSIONS = {'.wav', '.mp3', '.flac', '.m4a', '.ogg', '.opus', '.aac', '.webm'}
FORMATS = {'csv': 'result.csv', 'textgrid': 'result.TextGrid', 'txt': 'result.txt'}
STATIC_ROOT = Path(__file__).parent / 'static'


class BatchManifest(BaseModel):
    audio_names: list[str] = Field(default_factory=list)
    text_names: list[str] = Field(default_factory=list)
    language: str = ''


def _batch_pairs(manifest):
    if len(manifest.audio_names) + len(manifest.text_names) > 2000:
        raise HTTPException(400, '一个批次最多包含 1000 对文件')
    groups = {}
    for names, kind in ((manifest.audio_names, 'audio'), (manifest.text_names, 'text')):
        for name in names:
            if not name or len(name) > 255 or '/' in name or '\\' in name or name in {'.', '..'} or any(ord(c) < 32 for c in name):
                raise HTTPException(400, '文件名无效')
            path = Path(name)
            if (kind == 'audio' and path.suffix.lower() not in AUDIO_EXTENSIONS) or (kind == 'text' and path.suffix.lower() != '.txt'):
                raise HTTPException(400, '批量上传仅支持音频文件和 .txt 文本文件')
            key = unicodedata.normalize('NFC', path.stem).casefold()
            if not key:
                raise HTTPException(400, '文件名无效')
            groups.setdefault(key, {'audio': [], 'text': []})[kind].append(name)
    result = {'pairs': [], 'unmatched_audio': [], 'unmatched_text': [], 'duplicates': []}
    for key, group in groups.items():
        audios, texts = group['audio'], group['text']
        if len(audios) > 1 or len(texts) > 1:
            result['duplicates'].append({'stem': key, 'audio': audios, 'text': texts})
        elif audios and texts:
            result['pairs'].append({'audio': audios[0], 'text': texts[0]})
        elif audios:
            result['unmatched_audio'].extend(audios)
        else:
            result['unmatched_text'].extend(texts)
    return result


def _download_stem(audio_name):
    """Derive a safe, flat download name from the uploaded audio filename."""
    basename = str(audio_name).replace('\\', '/').rsplit('/', 1)[-1]
    stem = Path(basename).stem
    stem = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', '_', stem).strip(' .')
    return stem or 'audio'


def _audition_export(path):
    """Produce the Audition-compatible format for both old and new jobs."""
    try:
        return audition_csv_bytes(read_alignment_csv(path))
    except (OSError, UnicodeError, ValueError) as exc:
        LOG.exception('Invalid CSV result: %s', path)
        raise HTTPException(500, '对齐结果格式无效') from exc


def _attachment_disposition(filename):
    encoded = quote(filename)
    if encoded != filename:
        return f"attachment; filename*=utf-8''{encoded}"
    return f'attachment; filename="{filename}"'


class LimitBody:
    """Limit multipart bodies before Starlette can spool an oversized request."""
    def __init__(self, app, max_bytes):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope['headers'])
        try:
            length = int(headers.get(b'content-length', b'0'))
        except ValueError:
            length = self.max_bytes + 1
        if length > self.max_bytes:
            return await JSONResponse({'detail': '上传内容过大'}, status_code=413)(scope, receive, send)
        seen = 0
        async def limited_receive():
            nonlocal seen
            message = await receive()
            if message['type'] == 'http.request':
                seen += len(message.get('body', b''))
                if seen > self.max_bytes:
                    raise HTTPException(413, '上传内容过大')
            return message
        await self.app(scope, limited_receive, send)


def _default_runner(audio_path, text_path, language, output_dir):
    # CUDA contexts remain allocated for the lifetime of a Python process, even
    # after model objects and PyTorch's cache have been freed. Run each real job
    # in its own process so its entire context is released before marking the
    # job finished. Custom runners supplied to create_app remain in-process.
    with tempfile.TemporaryDirectory(prefix='mms-align-result-') as temp:
        result_file = Path(temp) / 'result.json'
        command = [sys.executable, '-m', 'alignment_web.worker', str(audio_path),
                   str(text_path), language, str(output_dir), str(result_file)]
        with tempfile.TemporaryFile(mode='w+b') as errors:
            process = subprocess.run(command, cwd=Path(__file__).resolve().parent.parent,
                                     stderr=errors, check=False)
            if process.returncode:
                errors.seek(0, os.SEEK_END)
                errors.seek(max(0, errors.tell() - 8000))
                detail = errors.read().decode('utf-8', errors='replace').strip()
                raise RuntimeError(detail[-2000:] or f'对齐进程异常退出（状态码 {process.returncode}）')
        try:
            return json.loads(result_file.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise RuntimeError('对齐进程未返回有效结果') from exc


def _default_converter(audio_path, destination):
    from alignment_core import convert_audio
    convert_audio(audio_path, destination)


def _private_file(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise ValueError('账户密钥文件须为当前用户所有且权限为 600')
        value = source.read(4097)
    if len(value) > 4096:
        raise ValueError('账户密钥文件过大')
    return value.strip()


def create_app(data_dir=None, runner=None, max_audio_bytes=None, auth_store=None, converter=None):
    data_dir = Path(data_dir or os.environ.get('ALIGN_WEB_DATA_DIR', 'service_data')).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir = data_dir / 'jobs'
    jobs_dir.mkdir(exist_ok=True)
    max_audio_bytes = max_audio_bytes if max_audio_bytes is not None else int(os.environ.get('ALIGN_WEB_MAX_AUDIO_MB', '2048')) * 1024 * 1024
    if max_audio_bytes <= 0:
        raise ValueError('ALIGN_WEB_MAX_AUDIO_MB must be positive')
    store = JobStore(data_dir / 'jobs.sqlite3')
    execute = runner or _default_runner
    convert = converter or _default_converter
    stop = threading.Event()
    wake = threading.Event()
    app = FastAPI(title='MMS Audio Alignment API', description='长音频与文本自动对齐服务。')
    app.add_middleware(LimitBody, max_bytes=max_audio_bytes + TEXT_LIMIT + FORM_OVERHEAD)
    app.mount('/static', StaticFiles(directory=STATIC_ROOT), name='static')
    if auth_store is None:
        secret_file = os.environ.get('ALIGN_AUTH_SECRET_FILE', '')
        smtp_file = os.environ.get('ALIGN_SMTP_PASSWORD_FILE', '')
        if bool(secret_file) != bool(smtp_file):
            raise ValueError('请同时配置账户密钥与邮件密码文件')
        if secret_file:
            secret = _private_file(secret_file)
            password = _private_file(smtp_file).decode('utf-8')
            if not password:
                raise ValueError('邮件密码文件为空')
            smtp_user = os.environ.get('ALIGN_SMTP_USER', 'duhu@dataoceanai.com')
            sender = SmtpCodeSender(os.environ.get('ALIGN_SMTP_HOST', 'smtp.qiye.aliyun.com'),
                                    int(os.environ.get('ALIGN_SMTP_PORT', '465')), smtp_user, password,
                                    os.environ.get('ALIGN_SMTP_FROM', smtp_user))
            auth_store = AuthStore(data_dir / 'accounts.sqlite3', secret, sender,
                                   admin_email=os.environ.get('ALIGN_ADMIN_EMAIL', 'duhu@dataoceanai.com'))
    app.state.store = store
    app.state.auth_store = auth_store
    app.state.auth_secure_cookie = os.environ.get('ALIGN_AUTH_SECURE_COOKIE', '0') == '1'
    app.include_router(auth_router)
    app.include_router(language_check_router)

    def job_dir(job_id):
        if not JOB_PATTERN.fullmatch(job_id):
            raise HTTPException(404, '任务不存在')
        return jobs_dir / job_id

    def job_audio(job):
        directory = job_dir(job['id'])
        normalized = directory / 'normalized.wav'
        # Existing jobs retain their original paths; new jobs use normalized WAV.
        return normalized if normalized.is_file() else directory / ('audio' + Path(job['audio_name']).suffix.lower())

    def get_job(job_id, user):
        job_dir(job_id)
        job = store.get(job_id)
        if job is None or (not user['is_admin'] and job['owner_id'] != user['id']):
            raise HTTPException(404, '任务不存在')
        if job['status'] == 'completed':
            job['artifacts'] = [name for name, filename in FORMATS.items() if (job_dir(job_id) / 'output' / filename).is_file()]
        else:
            job['artifacts'] = []
        return job

    def get_batch(batch_id, user):
        if not JOB_PATTERN.fullmatch(batch_id):
            raise HTTPException(404, '批次不存在')
        batch = store.get_batch(batch_id)
        if not batch or (not user['is_admin'] and batch['owner_id'] != user['id']):
            raise HTTPException(404, '批次不存在')
        return batch

    def statistics_for(job):
        try:
            directory = job_dir(job['id'])
            return audio_duration(job_audio(job)), output_sentences(directory / 'output' / FORMATS['csv'])
        except Exception:
            LOG.warning('Cannot collect statistics for job %s', job['id'], exc_info=True)
            return None, None

    def work():
        while not stop.is_set():
            job_id = store.claim()
            if job_id is None:
                wake.wait(2)
                wake.clear()
                continue
            job = store.get(job_id)
            directory = jobs_dir / job_id
            try:
                output = directory / 'output'
                output.mkdir(exist_ok=True)
                result = execute(job_audio(job),
                                 directory / 'input.txt', job['language'], output)
                if not isinstance(result, dict):
                    raise RuntimeError('对齐后端未返回结果文件')
                for kind, filename in FORMATS.items():
                    source = Path(result[kind])
                    if not source.is_file():
                        raise RuntimeError(f'缺少 {kind} 结果文件')
                    destination = output / filename
                    if source.resolve() != destination.resolve():
                        shutil.copyfile(source, destination)
                duration, sentence_count = statistics_for(job)
                store.finish(job_id, audio_seconds=duration, sentence_count=sentence_count)
            except Exception as exc:
                LOG.exception('Alignment job %s failed', job_id)
                store.finish(job_id, (str(exc) or type(exc).__name__)[:2000])

    def backfill_statistics():
        for job in store.incomplete_statistics():
            if stop.is_set():
                break
            try:
                store.fill_statistics(job['id'], *statistics_for(job))
            except (OSError, ValueError, HTTPException):
                LOG.warning('Cannot collect statistics for job %s', job['id'], exc_info=True)

    @app.on_event('startup')
    def startup():
        # Staging files can only be left behind by an interrupted upload/conversion.
        for path in jobs_dir.glob('*/.upload-*'):
            if JOB_PATTERN.fullmatch(path.parent.name) and path.is_file():
                path.unlink(missing_ok=True)
        store.recover()
        store.seed_completed_statistics()
        stop.clear()
        app.state.worker = threading.Thread(target=work, daemon=True, name='alignment-worker')
        app.state.worker.start()
        app.state.stats_worker = threading.Thread(target=backfill_statistics, daemon=True, name='alignment-stats-backfill')
        app.state.stats_worker.start()

    @app.on_event('shutdown')
    def shutdown():
        stop.set()
        wake.set()
        # A running alignment may take hours; it will be marked interrupted on restart.
        app.state.worker.join(timeout=1)
        app.state.stats_worker.join(timeout=1)
        from .fasttext_client import close as close_language_detector
        close_language_detector()

    @app.get('/', response_class=HTMLResponse, include_in_schema=False)
    def index():
        return (STATIC_ROOT / 'index.html').read_text(encoding='utf-8')

    @app.get('/health')
    def health():
        return {'ok': True}

    @app.get('/v1/languages')
    def languages():
        return {'languages': COMMON_LANGUAGES}

    @app.get('/api/admin/usage')
    def usage(user: dict = Depends(require_admin)):
        data = store.usage()
        normalized = set()
        for item in data['languages']:
            try:
                normalized.add(normalize_language(item['language']))
            except ValueError:
                normalized.add(item['language'])
        data['totals']['language_count'] = len(normalized)
        owners = {item['owner_id'] for item in data['users'] if item['owner_id']}
        usernames = app.state.auth_store.usernames_for_ids(owners) if app.state.auth_store else {}
        for item in data['users']:
            owner = item['owner_id']
            item['username'] = usernames.get(owner, '未知用户') if owner else '历史任务'
        return data

    @app.get('/v1/jobs')
    def list_jobs(limit: int = 50, offset: int = 0, status: Optional[str] = None,
                  language: Optional[str] = None, q: Optional[str] = None,
                  created_from: Optional[date] = None, created_to: Optional[date] = None,
                  owner_id: Optional[str] = None, batch_id: Optional[str] = None,
                  user: dict = Depends(require_account)):
        limit, offset = max(1, min(limit, 200)), max(0, offset)
        if owner_id and not user['is_admin']:
            raise HTTPException(403, '需要管理员权限')
        if status and status not in {'queued', 'running', 'completed', 'failed'}:
            raise HTTPException(400, '无效的任务状态')
        if created_from and created_to and created_from > created_to:
            raise HTTPException(400, '开始日期不能晚于结束日期')
        if batch_id:
            get_batch(batch_id, user)
        legacy_language = None
        if language:
            try:
                language = canonical_locale(language)
                legacy_language = normalize_language(language)
            except ValueError as exc:
                raise HTTPException(400, str(exc))
        jobs, total = store.list(limit, offset, status, language, q,
                                 str(created_from) if created_from else None,
                                 str(created_to) if created_to else None,
                                 owner_id=(None if owner_id == '__legacy__' else owner_id) if user['is_admin'] else user['id'],
                                 legacy_language=legacy_language,
                                 legacy_owner=owner_id == '__legacy__', batch_id=batch_id)
        jobs = [get_job(job['id'], user) for job in jobs]
        if user['is_admin']:
            owners = {job['owner_id'] for job in jobs if job['owner_id']}
            usernames = app.state.auth_store.usernames_for_ids(owners) if app.state.auth_store else {}
            for job in jobs:
                owner = job['owner_id']
                job['owner_username'] = usernames.get(owner, '未知用户') if owner else '历史任务'
        return {'jobs': jobs, 'total': total, 'limit': limit, 'offset': offset}

    @app.post('/v1/batches/check')
    def check_batch(manifest: BatchManifest, user: dict = Depends(require_account)):
        return _batch_pairs(manifest)

    @app.post('/v1/batches', status_code=201)
    def create_batch(manifest: BatchManifest, user: dict = Depends(require_account)):
        try:
            language = canonical_locale(manifest.language)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        result = _batch_pairs(manifest)
        if not result['pairs']:
            raise HTTPException(400, '没有可以上传的匹配文件')
        batch_id = uuid.uuid4().hex
        store.create_batch(batch_id, user['id'], language, result['pairs'])
        return {'batch_id': batch_id, **result}

    @app.get('/v1/batches')
    def list_batches(user: dict = Depends(require_account)):
        batches = store.list_batches(None if user['is_admin'] else user['id'])
        if user['is_admin']:
            owners = {batch['owner_id'] for batch in batches}
            usernames = app.state.auth_store.usernames_for_ids(owners) if app.state.auth_store else {}
            for batch in batches:
                batch['owner_username'] = usernames.get(batch['owner_id'], '未知用户')
        return {'batches': batches}

    def download_jobs(ids, selected, user):
        files = []
        used_stems = set()
        for job_id in ids:
            job = get_job(job_id, user)
            if job['status'] != 'completed':
                raise HTTPException(409, '只能下载已完成的任务')
            stem = _download_stem(job['audio_name'])
            unique_stem, index = stem, 2
            while unique_stem.casefold() in used_stems:
                unique_stem = f'{stem}_{index}'
                index += 1
            used_stems.add(unique_stem.casefold())
            for kind in selected:
                path = job_dir(job_id) / 'output' / FORMATS[kind]
                if not path.is_file():
                    raise HTTPException(404, '结果文件不存在')
                files.append((path, f'{unique_stem}{Path(FORMATS[kind]).suffix}'))
        temporary = tempfile.NamedTemporaryFile(prefix='alignment-export-', suffix='.zip', delete=False)
        temporary.close()
        try:
            with zipfile.ZipFile(temporary.name, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for path, archive_name in files:
                    if path.suffix.lower() == '.csv':
                        archive.writestr(archive_name, _audition_export(path))
                    else:
                        archive.write(path, archive_name)
        except BaseException:
            Path(temporary.name).unlink(missing_ok=True)
            raise
        return FileResponse(temporary.name, filename='alignment-results.zip', media_type='application/zip',
                            headers={'Cache-Control': 'no-store'},
                            background=BackgroundTask(Path(temporary.name).unlink, missing_ok=True))

    @app.get('/v1/jobs/bulk-artifacts.zip')
    def bulk_artifacts(job_ids: str, formats: str = 'csv', user: dict = Depends(require_account)):
        ids = list(dict.fromkeys(part.strip() for part in job_ids.split(',') if part.strip()))
        selected = list(dict.fromkeys(part.strip().lower() for part in formats.split(',') if part.strip()))
        if not ids or len(ids) > 200:
            raise HTTPException(400, '请选择 1 至 200 个任务')
        if not selected or any(kind not in FORMATS for kind in selected):
            raise HTTPException(400, '请选择有效的结果格式')
        return download_jobs(ids, selected, user)

    @app.get('/v1/batches/{batch_id}/artifacts.zip')
    def batch_artifacts(batch_id: str, formats: str = 'csv', user: dict = Depends(require_account)):
        get_batch(batch_id, user)
        selected = list(dict.fromkeys(part.strip().lower() for part in formats.split(',') if part.strip()))
        if not selected or any(kind not in FORMATS for kind in selected):
            raise HTTPException(400, '请选择有效的结果格式')
        ids = [job['id'] for job in store.batch_jobs(batch_id) if job['status'] == 'completed']
        if not ids:
            raise HTTPException(409, '批次中没有已完成的任务')
        return download_jobs(ids, selected, user)

    @app.post('/v1/jobs', status_code=202)
    async def create_job(audio: UploadFile = File(...), language: str = Form(...),
                         text: str = Form(''), text_file: Optional[UploadFile] = File(None),
                         batch_id: Optional[str] = Form(None),
                         user: dict = Depends(require_account)):
        try:
            language = canonical_locale(language)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if batch_id:
            batch = get_batch(batch_id, user)
            if batch['owner_id'] != user['id']:
                raise HTTPException(403, '只能向自己的批次提交任务')
            if batch['language'] != language or not text_file:
                raise HTTPException(400, '批次语种不一致或未上传文本文件')
            item = store.get_batch_item(batch_id, audio.filename, text_file.filename)
            if item is None:
                raise HTTPException(400, '文件不属于这个批次')
            if item['job_id']:
                existing = store.get(item['job_id'])
                if existing:
                    return {'job_id': existing['id'], 'status': existing['status']}
                raise HTTPException(409, '任务状态已改变，请重试')
        suffix = Path(audio.filename or '').suffix.lower()
        if suffix not in AUDIO_EXTENSIONS:
            raise HTTPException(400, '不支持的音频文件类型')
        if text_file and text.strip():
            raise HTTPException(400, '请填写文本或上传文本文件，二选一')
        if text_file:
            text_data = await text_file.read(TEXT_LIMIT + 1)
        else:
            text_data = text.encode('utf-8')
        if len(text_data) > TEXT_LIMIT:
            raise HTTPException(413, '文本文件过大')
        try:
            decoded = text_data.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise HTTPException(400, '文本文件必须采用 UTF-8 编码')
        if not decoded.strip() or '\x00' in decoded:
            raise HTTPException(400, '文本不能为空或包含 NUL 字符')
        job_id = uuid.uuid4().hex
        directory = jobs_dir / job_id
        directory.mkdir(mode=0o700)
        try:
            size = 0
            original = directory / ('.upload-' + uuid.uuid4().hex + suffix)
            with original.open('wb') as target:
                while True:
                    chunk = await audio.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_audio_bytes:
                        raise HTTPException(413, '音频文件过大')
                    target.write(chunk)
            if size == 0:
                raise HTTPException(400, '音频文件为空')
            try:
                await run_in_threadpool(convert, original, directory / 'normalized.wav')
            except ValueError as exc:
                raise HTTPException(400, f'音频转换失败：{exc}') from exc
            original.unlink()
            (directory / 'input.txt').write_text(decoded, encoding='utf-8')
            try:
                created_id = store.create(job_id, language, Path(audio.filename or 'audio').stem[:200] + suffix,
                                          user['id'], batch_id, audio.filename, text_file.filename if text_file else None)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            if created_id != job_id:
                shutil.rmtree(directory, ignore_errors=True)
                job_id = created_id
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        finally:
            await audio.close()
            if text_file:
                await text_file.close()
        wake.set()
        current = store.get(job_id)
        if current is None:
            raise HTTPException(409, '任务状态已改变，请重试')
        return {'job_id': job_id, 'status': current['status']}

    @app.get('/v1/jobs/{job_id}')
    def job_detail(job_id: str, user: dict = Depends(require_account)):
        return get_job(job_id, user)

    @app.post('/v1/jobs/{job_id}/retry')
    def retry_job(job_id: str, user: dict = Depends(require_account)):
        job = get_job(job_id, user)
        if job['status'] != 'failed':
            raise HTTPException(409, '只有失败的任务可以重试')
        if not job_audio(job).is_file() or not (job_dir(job_id) / 'input.txt').is_file():
            raise HTTPException(404, '输入文件不存在')
        if not store.retry(job_id):
            raise HTTPException(409, '任务状态已改变')
        wake.set()
        return get_job(job_id, user)

    @app.get('/v1/jobs/{job_id}/sentences')
    def sentences(job_id: str, user: dict = Depends(require_account)):
        job = get_job(job_id, user)
        path = job_dir(job_id) / 'output' / FORMATS['csv']
        if job['status'] != 'completed' or not path.is_file():
            raise HTTPException(404, '对齐结果不存在')
        try:
            return read_alignment_csv(path)
        except (OSError, UnicodeError, ValueError) as exc:
            LOG.exception('Invalid CSV result for job %s', job_id)
            raise HTTPException(500, '对齐结果格式无效') from exc

    @app.get('/v1/jobs/{job_id}/input/{kind}')
    def input_file(job_id: str, kind: str, user: dict = Depends(require_account)):
        job = get_job(job_id, user)
        if kind == 'audio':
            path = job_audio(job)
        elif kind == 'text':
            path = job_dir(job_id) / 'input.txt'
        else:
            raise HTTPException(404, '输入文件不存在')
        if not path.is_file():
            raise HTTPException(404, '输入文件不存在')
        return FileResponse(path, media_type='text/plain; charset=utf-8' if kind == 'text' else None)

    @app.get('/v1/jobs/{job_id}/waveform')
    def job_waveform(job_id: str, points: int = Query(4000, ge=1, le=48000),
                     user: dict = Depends(require_account)):
        job = get_job(job_id, user)
        path = job_audio(job)
        if not path.is_file():
            raise HTTPException(404, '音频文件不存在')
        try:
            from .waveform import waveform
            return waveform(path, points)
        except (ValueError, OSError, EOFError, wave.Error) as exc:
            LOG.warning('Cannot read waveform for job %s: %s', job_id, exc)
            raise HTTPException(422, '无法读取音频波形') from exc

    @app.get('/v1/jobs/{job_id}/artifacts/{kind}')
    def artifact(job_id: str, kind: str, user: dict = Depends(require_account)):
        job = get_job(job_id, user)
        if job['status'] != 'completed' or kind not in FORMATS:
            raise HTTPException(404, '结果文件不存在')
        path = job_dir(job_id) / 'output' / FORMATS[kind]
        if not path.is_file():
            raise HTTPException(404, '结果文件不存在')
        filename = f'{_download_stem(job["audio_name"])}{Path(FORMATS[kind]).suffix}'
        if kind == 'csv':
            return Response(_audition_export(path), media_type='application/octet-stream',
                            headers={'Content-Disposition': _attachment_disposition(filename),
                                     'Cache-Control': 'no-store'})
        return FileResponse(path, filename=filename,
                            media_type='application/octet-stream')

    @app.delete('/v1/jobs/{job_id}')
    def delete_job(job_id: str, user: dict = Depends(require_account)):
        job = get_job(job_id, user)
        if not user['is_admin']:
            raise HTTPException(403, '只有管理员可以删除任务')
        if not store.delete(job_id):
            raise HTTPException(409, '排队中或运行中的任务不能删除')
        shutil.rmtree(job_dir(job_id), ignore_errors=True)
        return {'deleted': job['id']}

    return app


def main():
    import uvicorn
    uvicorn.run(create_app(), host=os.environ.get('ALIGN_WEB_HOST', '0.0.0.0'),
                port=int(os.environ.get('ALIGN_WEB_PORT', '10076')))


if __name__ == '__main__':
    main()

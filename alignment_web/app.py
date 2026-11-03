"""Single-process HTTP service. No authentication is provided."""
import logging
import os
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from alignment_languages import COMMON_LANGUAGES, normalize_language

from .store import JobStore

LOG = logging.getLogger(__name__)
TEXT_LIMIT = 2 * 1024 * 1024
FORM_OVERHEAD = 1024 * 1024
JOB_PATTERN = re.compile(r'^[0-9a-f]{32}$')
AUDIO_EXTENSIONS = {'.wav', '.mp3', '.flac', '.m4a', '.ogg', '.opus', '.aac', '.webm'}
FORMATS = {'csv': 'result.csv', 'textgrid': 'result.TextGrid', 'txt': 'result.txt'}
STATIC_ROOT = Path(__file__).parent / 'static'


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
    from alignment_core import align
    return align(audio_path, text_path, language, output_dir)


def create_app(data_dir=None, runner=None, max_audio_bytes=None):
    data_dir = Path(data_dir or os.environ.get('ALIGN_WEB_DATA_DIR', 'service_data')).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir = data_dir / 'jobs'
    jobs_dir.mkdir(exist_ok=True)
    max_audio_bytes = max_audio_bytes if max_audio_bytes is not None else int(os.environ.get('ALIGN_WEB_MAX_AUDIO_MB', '2048')) * 1024 * 1024
    if max_audio_bytes <= 0:
        raise ValueError('ALIGN_WEB_MAX_AUDIO_MB must be positive')
    store = JobStore(data_dir / 'jobs.sqlite3')
    execute = runner or _default_runner
    stop = threading.Event()
    wake = threading.Event()
    app = FastAPI(title='MMS Audio Alignment API', description='长音频与文本自动对齐服务。')
    app.add_middleware(LimitBody, max_bytes=max_audio_bytes + TEXT_LIMIT + FORM_OVERHEAD)
    app.mount('/static', StaticFiles(directory=STATIC_ROOT), name='static')
    app.state.store = store

    def job_dir(job_id):
        if not JOB_PATTERN.fullmatch(job_id):
            raise HTTPException(404, '任务不存在')
        return jobs_dir / job_id

    def get_job(job_id):
        job_dir(job_id)
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, '任务不存在')
        if job['status'] == 'completed':
            job['artifacts'] = [name for name, filename in FORMATS.items() if (job_dir(job_id) / 'output' / filename).is_file()]
        else:
            job['artifacts'] = []
        return job

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
                result = execute(directory / ('audio' + Path(job['audio_name']).suffix.lower()),
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
                store.finish(job_id)
            except Exception as exc:
                LOG.exception('Alignment job %s failed', job_id)
                store.finish(job_id, (str(exc) or type(exc).__name__)[:2000])

    @app.on_event('startup')
    def startup():
        store.recover()
        stop.clear()
        app.state.worker = threading.Thread(target=work, daemon=True, name='alignment-worker')
        app.state.worker.start()

    @app.on_event('shutdown')
    def shutdown():
        stop.set()
        wake.set()
        # A running alignment may take hours; it will be marked interrupted on restart.
        app.state.worker.join(timeout=1)

    @app.get('/', response_class=HTMLResponse, include_in_schema=False)
    def index():
        return (STATIC_ROOT / 'index.html').read_text(encoding='utf-8')

    @app.get('/health')
    def health():
        return {'ok': True}

    @app.get('/v1/languages')
    def languages():
        return {'languages': COMMON_LANGUAGES}

    @app.get('/v1/jobs')
    def list_jobs(limit: int = 50, offset: int = 0):
        limit, offset = max(1, min(limit, 200)), max(0, offset)
        jobs, total = store.list(limit, offset)
        return {'jobs': [get_job(job['id']) for job in jobs], 'total': total, 'limit': limit, 'offset': offset}

    @app.post('/v1/jobs', status_code=202)
    async def create_job(audio: UploadFile = File(...), language: str = Form(...),
                         text: str = Form(''), text_file: Optional[UploadFile] = File(None)):
        try:
            language = normalize_language(language)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
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
            with (directory / ('audio' + suffix)).open('wb') as target:
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
            (directory / 'input.txt').write_text(decoded, encoding='utf-8')
            store.create(job_id, language, Path(audio.filename or 'audio').stem[:200] + suffix)
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        finally:
            await audio.close()
            if text_file:
                await text_file.close()
        wake.set()
        return {'job_id': job_id, 'status': 'queued'}

    @app.get('/v1/jobs/{job_id}')
    def job_detail(job_id: str):
        return get_job(job_id)

    @app.get('/v1/jobs/{job_id}/input/{kind}')
    def input_file(job_id: str, kind: str):
        job = get_job(job_id)
        if kind == 'audio':
            path = job_dir(job_id) / ('audio' + Path(job['audio_name']).suffix.lower())
        elif kind == 'text':
            path = job_dir(job_id) / 'input.txt'
        else:
            raise HTTPException(404, '输入文件不存在')
        if not path.is_file():
            raise HTTPException(404, '输入文件不存在')
        return FileResponse(path, media_type='text/plain; charset=utf-8' if kind == 'text' else None)

    @app.get('/v1/jobs/{job_id}/artifacts/{kind}')
    def artifact(job_id: str, kind: str):
        job = get_job(job_id)
        if job['status'] != 'completed' or kind not in FORMATS:
            raise HTTPException(404, '结果文件不存在')
        path = job_dir(job_id) / 'output' / FORMATS[kind]
        if not path.is_file():
            raise HTTPException(404, '结果文件不存在')
        return FileResponse(path, filename=FORMATS[kind], media_type='application/octet-stream')

    @app.delete('/v1/jobs/{job_id}')
    def delete_job(job_id: str):
        job = get_job(job_id)
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

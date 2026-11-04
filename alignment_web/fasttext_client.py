"""Bounded, private IPC for the optional local fastText language identifier."""
import atexit
import json
import os
from pathlib import Path
import selectors
import subprocess
from threading import Lock
import time


class FastTextClient:
    def __init__(self, python, model, timeout=30.0):
        self.python, self.model, self.timeout = python, model, timeout
        self.process = None
        self.lock = Lock()
        self.failed_until = 0.0

    def _stop(self):
        process, self.process = self.process, None
        if process is None:
            return
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        for pipe in (process.stdin, process.stdout):
            if pipe is not None:
                pipe.close()

    def close(self):
        with self.lock:
            self._stop()

    def _start(self):
        env = os.environ.copy()
        env['CUDA_VISIBLE_DEVICES'] = ''
        worker = Path(__file__).with_name('fasttext_worker.py')
        self.process = subprocess.Popen(
            [self.python, '-u', str(worker), self.model],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=0, env=env,
        )
        os.set_blocking(self.process.stdin.fileno(), False)
        os.set_blocking(self.process.stdout.fileno(), False)

    def predict(self, pieces):
        """Return predictions or None; no transcript is retained after the call."""
        if not self.lock.acquire(timeout=self.timeout):
            return None
        try:
            if time.monotonic() < self.failed_until:
                return None
            try:
                if self.process is None or self.process.poll() is not None:
                    self._stop()
                    self._start()
                process = self.process
                request = (json.dumps({'pieces': pieces}, ensure_ascii=True) + '\n').encode()
                deadline = time.monotonic() + self.timeout
                data = bytearray()
                offset = 0
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdin, selectors.EVENT_WRITE)
                    selector.register(process.stdout, selectors.EVENT_READ)
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError
                        for key, _ in selector.select(remaining):
                            if key.fileobj is process.stdin:
                                offset += os.write(process.stdin.fileno(), request[offset:])
                                if offset == len(request):
                                    selector.unregister(process.stdin)
                            else:
                                chunk = os.read(process.stdout.fileno(), 65536)
                                if not chunk:
                                    raise EOFError
                                data.extend(chunk)
                                if len(data) > 65536:
                                    raise ValueError('oversized response')
                                if b'\n' in data:
                                    response = json.loads(data.split(b'\n', 1)[0])
                                    if (not isinstance(response, dict) or
                                            not isinstance(response.get('labels'), list) or
                                            not isinstance(response.get('predictions'), list)):
                                        raise ValueError('invalid response')
                                    return response
            except (OSError, EOFError, TimeoutError, ValueError, TypeError, KeyError):
                self._stop()
                self.failed_until = time.monotonic() + 5
                return None
        finally:
            self.lock.release()


_client = None
_config_lock = Lock()


def predict(pieces):
    global _client
    python = os.environ.get('ALIGN_LANGUAGE_FASTTEXT_PYTHON', '')
    model = os.environ.get('ALIGN_LANGUAGE_FASTTEXT_MODEL', '')
    with _config_lock:
        if not python or not model:
            if _client is not None:
                _client.close()
                _client = None
            return None
        if _client is None or (_client.python, _client.model) != (python, model):
            if _client is not None:
                _client.close()
            _client = FastTextClient(python, model)
        client = _client
    return client.predict(pieces)


def close():
    global _client
    with _config_lock:
        if _client is not None:
            _client.close()
            _client = None


atexit.register(close)

"""HTTPS is terminated by the hosting platform/reverse proxy, not this process."""
import json
import logging
import os
import sqlite3
import time
from collections import OrderedDict, deque
from pathlib import Path
from threading import Lock
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from core.auth import AuthError, HardwareMismatch
from server.service import ServerAuth, SessionDenied

log = logging.getLogger(__name__)


class Device(BaseModel):
    hwid: str = Field(pattern=r'^[0-9a-f]{64}$')


class Activation(Device):
    login: str = Field(min_length=2, max_length=40)
    code: str = Field(min_length=12, max_length=12)


class ResetRequest(Activation):
    reason: str = Field(min_length=1, max_length=2000)


class RateLimiter:
    def __init__(self, limit=30, window=300):
        self.limit, self.window = limit, window
        self.entries, self.lock = OrderedDict(), Lock()

    def check(self, key):
        with self.lock:
            now = time.monotonic()
            events = self.entries.setdefault(key, deque())
            while events and events[0] < now - self.window:
                events.popleft()
            if len(events) >= self.limit:
                raise HTTPException(429, detail={'message': 'Слишком много попыток. Повторите позже.'})
            events.append(now)
            self.entries.move_to_end(key)
            while len(self.entries) > 10000:
                self.entries.popitem(last=False)


async def read_payload(request, model):
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 8192:
            raise HTTPException(413, detail={'message': 'Запрос слишком большой.'})
        body.extend(chunk)
    try:
        return model.model_validate(json.loads(body))
    except (ValueError, ValidationError):
        raise HTTPException(422, detail={'message': 'Некорректные поля запроса.'})


def create_app(db_path=None, *, rate_limit=30):
    app = FastAPI(title='MangaFlow Access', docs_url=None, redoc_url=None, openapi_url=None)
    path = Path(db_path or os.getenv('MF_AUTH_DB', 'server/data/auth.db')).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    service = ServerAuth(path)
    limiter = RateLimiter(rate_limit)
    app.state.auth = service

    @app.middleware('http')
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.exception_handler(AuthError)
    async def auth_error(request, exc):
        code = 'hardware_mismatch' if isinstance(exc, HardwareMismatch) else 'session_denied' if isinstance(exc, SessionDenied) else 'auth_error'
        status = 409 if isinstance(exc, HardwareMismatch) else 401 if isinstance(exc, SessionDenied) else 400
        return JSONResponse(status_code=status, content={'detail': {'code': code, 'message': str(exc)}})

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, exc):
        log.exception('Ошибка БД сервера авторизации')
        return JSONResponse(status_code=503, content={'detail': {'message': 'Сервис временно недоступен.'}})

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.post('/v1/activate')
    async def activate(request: Request):
        limiter.check(request.client.host if request.client else 'unknown')
        data = await read_payload(request, Activation)
        return await run_in_threadpool(service.activate, data.login, data.code, data.hwid)

    @app.post('/v1/session')
    async def validate(request: Request):
        data = await read_payload(request, Device)
        header = request.headers.get('Authorization', '')
        if not header.startswith('Bearer ') or not 20 <= len(header[7:]) <= 256:
            raise SessionDenied('Необходима авторизация.')
        return await run_in_threadpool(service.validate, header[7:], data.hwid)

    @app.post('/v1/reset-requests')
    async def request_reset(request: Request):
        limiter.check(request.client.host if request.client else 'unknown')
        data = await read_payload(request, ResetRequest)
        return await run_in_threadpool(service.request_reset, data.login, data.code, data.hwid, data.reason)

    return app

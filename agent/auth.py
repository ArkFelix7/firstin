"""Optional access-code auth for the hosted deployment (deploy/DEPLOY.md).

Off unless env FIRSTIN_ACCESS_CODE is set. When on, every route except GET /health and CORS
preflights needs one of:
  - Authorization: Bearer <code>
  - Authorization: Basic base64(<any user>:<code>)   (browser prompt / curl -u x:<code>)
  - ?key=<code>   only on /stream/*, /static/*, /incab/active, because EventSource, <audio>
                  and <img> can't send headers.
Comparisons are constant-time. Pure ASGI middleware (no buffering, so SSE is untouched).
"""
from __future__ import annotations

import base64
import binascii
import hmac
import os
from urllib.parse import parse_qs

OPEN_PATHS = ("/health",)
KEY_PREFIXES = ("/stream/", "/static/")
KEY_PATHS = ("/incab/active",)


def access_code() -> str | None:
    return os.environ.get("FIRSTIN_ACCESS_CODE", "").strip() or None


def _eq(given: str | None, code: str) -> bool:
    return given is not None and hmac.compare_digest(given.encode(), code.encode())


def header_ok(value: str | None, code: str) -> bool:
    if not value:
        return False
    scheme, _, token = value.strip().partition(" ")
    scheme, token = scheme.lower(), token.strip()
    if scheme == "bearer":
        return _eq(token, code)
    if scheme == "basic":
        try:
            pair = base64.b64decode(token + "=" * (-len(token) % 4)).decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            return False
        return ":" in pair and _eq(pair.partition(":")[2], code)
    return False


def key_allowed(path: str) -> bool:
    return path.startswith(KEY_PREFIXES) or path in KEY_PATHS


def key_ok(query_string: bytes, code: str) -> bool:
    keys = parse_qs(query_string.decode("latin-1")).get("key") or []
    return any(_eq(k, code) for k in keys)


class AccessCodeMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        code = access_code()
        if code is None:
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        if path in OPEN_PATHS or (scope.get("method") == "OPTIONS" and "access-control-request-method" in headers):
            return await self.app(scope, receive, send)
        if header_ok(headers.get("authorization"), code):
            return await self.app(scope, receive, send)
        if key_allowed(path) and key_ok(scope.get("query_string", b""), code):
            return await self.app(scope, receive, send)
        out = [(b"content-type", b"application/json")]
        if "origin" not in headers:  # direct browser visit gets a prompt; cross-origin fetch gets a plain 401
            out.append((b"www-authenticate", b'Basic realm="FirstIn (password = access code)", charset="UTF-8"'))
        await send({"type": "http.response.start", "status": 401, "headers": out})
        await send({"type": "http.response.body", "body": b'{"detail":"access code required"}'})

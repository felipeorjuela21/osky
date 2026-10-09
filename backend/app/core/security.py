"""Protections for the public deployment: per-visitor rate limit and admin token."""
import hmac
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request

from backend.app.core.config import settings

_hits: dict[str, deque] = defaultdict(deque)

def client_ip(request: Request) -> str:
    # Render/Cloudflare put the real visitor IP first in X-Forwarded-For.
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")

def rate_limit(request: Request) -> None:
    """At most RATE_LIMIT_PER_MINUTE calls per visitor to the costly endpoints."""
    limit = settings.rate_limit_per_minute
    if limit <= 0:
        return
    now = time.monotonic()
    hits = _hits[client_ip(request)]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= limit:
        raise HTTPException(status_code=429, detail="Muchas preguntas seguidas. Espera un momento, por favor.")
    hits.append(now)
    if len(_hits) > 10_000:  # keep memory bounded on the small free server
        for ip in [ip for ip, h in _hits.items() if not h or now - h[-1] > 60]:
            _hits.pop(ip, None)

def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Admin endpoints need ADMIN_TOKEN (always in production; optional in development)."""
    expected = settings.admin_token
    if not expected:
        if settings.is_production:
            raise HTTPException(status_code=403, detail="Configura ADMIN_TOKEN para usar esta función.")
        return
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Token de administrador inválido.")

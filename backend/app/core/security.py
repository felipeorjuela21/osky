"""Protections for the public deployment: per-visitor rate limits, a global cap and the admin token."""
import hmac
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request

from backend.app.core.config import settings

_hits: dict[str, deque] = defaultdict(deque)
_global_hits: deque = deque()
_failures: dict[str, deque] = defaultdict(deque)

TOO_MANY = "Muchas preguntas seguidas. Espera un momento, por favor."
ADMIN_MAX_FAILS = 10
ADMIN_WINDOW = 600  # seconds

def client_ip(request: Request) -> str:
    """The visitor's IP. The client controls the START of X-Forwarded-For, so it is read from the
    END: each proxy appends the address it received the request from (TRUSTED_PROXY_HOPS = proxies
    we run behind). Uvicorn's request.client is not used: with --forwarded-allow-ips "*" it takes
    the first (forgeable) value."""
    hosts = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    if hosts:
        return hosts[-min(max(settings.trusted_proxy_hops, 1), len(hosts))]
    return request.client.host if request.client else "unknown"

def _allow(bucket: deque, limit: int, now: float, window: float = 60) -> bool:
    while bucket and now - bucket[0] > window:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True

def _prune(table: dict, now: float, window: float = 60) -> None:
    if len(table) > 10_000:  # keep memory bounded on the small free server
        for key in [k for k, h in table.items() if not h or now - h[-1] > window]:
            table.pop(key, None)

def _check(request: Request, scope: str, limit: int, costly: bool = True) -> None:
    now = time.monotonic()
    # Per visitor first: requests rejected here must not use up the global cap for everyone.
    if limit > 0:
        key = f"{scope}:{client_ip(request)}"
        if not _allow(_hits[key], limit, now):
            raise HTTPException(status_code=429, detail=TOO_MANY)
        _prune(_hits, now)
    if costly and settings.global_rate_limit_per_minute > 0 and not _allow(
            _global_hits, settings.global_rate_limit_per_minute, now):
        raise HTTPException(status_code=429, detail="Estoy con mucha demanda. Intenta de nuevo en un momento.")

def rate_limit(request: Request) -> None:
    """At most RATE_LIMIT_PER_MINUTE calls per visitor to the costly endpoints (ask)."""
    _check(request, "ask", settings.rate_limit_per_minute)

def rate_limit_light(request: Request) -> None:
    """Conversation bookkeeping (no Groq call): its own per-visitor bucket, not in the global cap."""
    _check(request, "light", settings.rate_limit_per_minute * 2, costly=False)

def rate_limit_media(request: Request) -> None:
    """Voice endpoints (tts/stt): a spoken turn makes several calls, so the limit is higher.
    Only stt uses Groq, so only stt counts toward the global cap (tts is edge-tts)."""
    _check(request, "media", settings.media_rate_limit_per_minute, costly=str(request.scope.get("path", "")).endswith("/stt"))

def require_admin(request: Request, x_admin_token: str | None = Header(default=None)) -> None:
    """Admin endpoints need ADMIN_TOKEN (always in production; optional in development)."""
    expected = settings.admin_token
    if not expected:
        if settings.is_production:
            raise HTTPException(status_code=403, detail="Configura ADMIN_TOKEN para usar esta función.")
        return
    now = time.monotonic()
    fails = _failures[client_ip(request)]
    while fails and now - fails[0] > ADMIN_WINDOW:
        fails.popleft()
    if len(fails) >= ADMIN_MAX_FAILS:
        raise HTTPException(status_code=429, detail="Demasiados intentos. Espera unos minutos.")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        fails.append(now)
        _prune(_failures, now, ADMIN_WINDOW)
        raise HTTPException(status_code=401, detail="Token de administrador inválido.")

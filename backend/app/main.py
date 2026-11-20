import json
import logging
from threading import Lock
from time import monotonic, time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.db import engine
from app.literature import router as literature
from app.research import router as research
from app.workspace import router as workspace

config = settings()
app = FastAPI(title="ResearchPilot AI", version="0.1.0")
for router in workspace, literature, research:
    app.include_router(router, prefix="/api/v1")

redis = Redis.from_url(config.redis_url, socket_connect_timeout=1, socket_timeout=1) if config.redis_url else None
local_rates = {}
rate_lock = Lock()
latency = Histogram("researchpilot_http_seconds", "Request duration", ("method",))
requests = Counter("researchpilot_http_requests", "Request count", ("method", "status"))
logger = logging.getLogger("researchpilot.http")
logger.setLevel(logging.INFO)
logger.propagate = False
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(handler)
increment = """
local value = redis.call('INCR', KEYS[1])
if value == 1 then redis.call('EXPIRE', KEYS[1], 70) end
return value
"""


def quota(key, maximum):
    window = int(time() // 60)
    if redis:
        return redis.eval(increment, 1, f"rp:limits:{window}:{key}") <= maximum
    with rate_lock:
        if local_rates.get("window") != window:
            local_rates.clear()
            local_rates["window"] = window
        local_rates[key] = local_rates.get(key, 0) + 1
        return local_rates[key] <= maximum


@app.middleware("http")
async def controls(request: Request, call_next):
    start = monotonic()
    path = request.url.path
    method = request.method
    if path.startswith("/api/v1/"):
        origin = request.headers.get("origin")
        if method not in ("GET", "HEAD", "OPTIONS") and origin:
            expected = config.origin or str(request.base_url).rstrip("/")
            if origin != expected:
                return JSONResponse({"detail": "Request origin is not allowed"}, status_code=403)
        ip = request.client.host if request.client else "unknown"
        auth = path.endswith(("/auth/login", "/auth/register"))
        try:
            from starlette.concurrency import run_in_threadpool
            allowed = await run_in_threadpool(quota, f"{ip}:{'auth' if auth else 'api'}", 12 if auth else 180)
        except RedisError:
            return JSONResponse({"detail": "Rate limit service unavailable"}, status_code=503)
        if not allowed:
            return JSONResponse({"detail": "Request limit reached"}, status_code=429, headers={"Retry-After": "60"})

    response = await call_next(request)
    elapsed = monotonic() - start
    method_label = method if method in ("GET", "HEAD", "OPTIONS", "POST", "PATCH", "DELETE", "PUT") else "OTHER"
    latency.labels(method_label).observe(elapsed)
    requests.labels(method_label, response.status_code).inc()
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if path.startswith("/api/v1/"):
        response.headers["Cache-Control"] = "no-store"
    logger.info(json.dumps({"event": "http_request", "method": method_label,
                            "status": response.status_code, "duration_ms": round(elapsed * 1000)}))
    return response


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT id FROM users WHERE 1 = 0"))
        if redis:
            redis.ping()
    except (SQLAlchemyError, RedisError):
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ready"}


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

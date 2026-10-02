import logging
import time
import uuid

from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.request_limits import allow_request

log = logging.getLogger("uvicorn.error.requests")


async def request_middleware(request, call_next):
    request_id = uuid.uuid4().hex
    started = time.monotonic()
    path = request.url.path
    if (
        settings.RATE_LIMIT_ENABLED
        and request.method != "OPTIONS"
        and path.startswith(settings.API_V1_STR)
    ):
        group = (
            "auth"
            if path.startswith(settings.API_V1_STR + "/auth/") and request.method != "GET"
            else ("read" if request.method == "GET" else "write")
        )
        maximum = {
            "auth": settings.RATE_LIMIT_AUTH_PER_MINUTE,
            "read": settings.RATE_LIMIT_READ_PER_MINUTE,
            "write": settings.RATE_LIMIT_WRITE_PER_MINUTE,
        }[group]
        identity = f"{request.client.host if request.client else 'unknown'}:{group}"
        async with AsyncSessionLocal() as db:
            allowed, retry = await allow_request(db, identity, maximum)
        if not allowed:
            return JSONResponse(
                {"detail": "Çok fazla istek. Biraz sonra tekrar deneyin."},
                status_code=429,
                headers={"Retry-After": str(retry), "X-Request-ID": request_id},
            )
    try:
        response = await call_next(request)
    except Exception:
        # Never log query strings, password bodies, bearer tokens or account links.
        log.exception("request_failed id=%s method=%s path=%s", request_id, request.method, path)
        return JSONResponse(
            {"detail": "İşlem tamamlanamadı.", "request_id": request_id},
            status_code=500,
            headers={"X-Request-ID": request_id},
        )
    response.headers["X-Request-ID"] = request_id
    log.info(
        "request id=%s method=%s path=%s status=%s ms=%d",
        request_id,
        request.method,
        path,
        response.status_code,
        int((time.monotonic() - started) * 1000),
    )
    return response

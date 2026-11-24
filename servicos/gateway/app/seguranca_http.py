"""Cabeçalhos de segurança, limite de payload e rastreio por Request-ID no Gateway."""
import logging
import re
import time
import uuid
from contextvars import ContextVar

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import TAMANHO_MAXIMO_REQUISICAO

log = logging.getLogger("helpdesk.gateway")
_PADRAO_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

CSP_TELA = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
CSP_DOCS = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
    "frame-ancestors 'none'; base-uri 'none'"
)


def obter_ou_gerar_request_id(valor: str | None) -> str:
    if valor and _PADRAO_REQUEST_ID.match(valor.strip()):
        return valor.strip()
    return uuid.uuid4().hex


class CabecalhosDeSeguranca(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        req_id = obter_ou_gerar_request_id(request.headers.get("x-request-id"))
        token_ctx = request_id_ctx.set(req_id)
        inicio = time.perf_counter()
        try:
            tamanho = request.headers.get("content-length")
            if tamanho and (not tamanho.isdigit() or int(tamanho) > TAMANHO_MAXIMO_REQUISICAO):
                return JSONResponse(status_code=413, content={"detail": "Requisição grande demais."})

            resposta = await call_next(request)
            documentacao = request.url.path in ("/docs", "/redoc", "/openapi.json")
            resposta.headers["Content-Security-Policy"] = CSP_DOCS if documentacao else CSP_TELA
            resposta.headers["X-Content-Type-Options"] = "nosniff"
            resposta.headers["X-Frame-Options"] = "DENY"
            resposta.headers["Referrer-Policy"] = "no-referrer"
            resposta.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            resposta.headers["Cross-Origin-Opener-Policy"] = "same-origin"
            resposta.headers["X-Request-ID"] = req_id
            if request.headers.get("authorization"):
                resposta.headers["Cache-Control"] = "no-store"

            duracao_ms = round((time.perf_counter() - inicio) * 1000, 1)
            log.info(
                "request_id=%s metodo=%s rota=%s status=%s duracao_ms=%s",
                req_id, request.method, request.url.path, resposta.status_code, duracao_ms,
            )
            return resposta
        finally:
            request_id_ctx.reset(token_ctx)

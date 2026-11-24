"""Roteamento reverso e agregação de saúde do API Gateway."""
import asyncio
import time

import httpx
from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app import config
from app.seguranca_http import request_id_ctx

_cliente_async: httpx.AsyncClient | None = None


def servicos_destinos() -> dict[str, str]:
    return {
        "usuarios": config.USUARIOS_URL,
        "inventario": config.INVENTARIO_URL,
        "chamados": config.CHAMADOS_URL,
        "notificacoes": config.NOTIFICACOES_URL,
    }


def resolver_destino(caminho: str) -> tuple[str, str] | None:
    """Mapeia o prefixo da rota para o microsserviço responsável."""
    destinos = servicos_destinos()
    regras = (
        ("/auth", "usuarios"),
        ("/usuarios", "usuarios"),
        ("/ativos", "inventario"),
        ("/chamados", "chamados"),
        ("/notificacoes", "notificacoes"),
    )
    for prefixo, servico in regras:
        if caminho == prefixo or caminho.startswith(prefixo + "/"):
            return servico, destinos[servico]
    return None


def obter_cliente_http() -> httpx.AsyncClient:
    global _cliente_async
    if _cliente_async is None or _cliente_async.is_closed:
        _cliente_async = httpx.AsyncClient(timeout=config.GATEWAY_TIMEOUT_SEGUNDOS)
    return _cliente_async


async def fechar_cliente_http() -> None:
    global _cliente_async
    if _cliente_async is not None and not _cliente_async.is_closed:
        await _cliente_async.aclose()
        _cliente_async = None


async def encaminhar(request: Request) -> Response:
    alvo = resolver_destino(request.url.path)
    if alvo is None:
        return JSONResponse(status_code=404, content={"detail": "Rota não encontrada."})

    nome_servico, base_url = alvo
    corpo = await request.body()
    if len(corpo) > config.TAMANHO_MAXIMO_REQUISICAO:
        return JSONResponse(status_code=413, content={"detail": "Requisição grande demais."})

    req_id = request_id_ctx.get()
    cabecalhos: dict[str, str] = {"X-Request-ID": req_id}
    for chave in ("authorization", "content-type", "accept"):
        valor = request.headers.get(chave)
        if valor:
            cabecalhos[chave] = valor

    ip_cliente = request.client.host if request.client else ""
    xff_anterior = request.headers.get("x-forwarded-for")
    if xff_anterior and ip_cliente:
        cabecalhos["x-forwarded-for"] = f"{xff_anterior}, {ip_cliente}"
    elif ip_cliente:
        cabecalhos["x-forwarded-for"] = ip_cliente

    url_destino = f"{base_url}{request.url.path}"
    if request.url.query:
        url_destino += f"?{request.url.query}"

    cliente = obter_cliente_http()
    try:
        resp = await cliente.request(
            method=request.method,
            url=url_destino,
            headers=cabecalhos,
            content=corpo if corpo else None,
        )
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content={
                "detail": f"O serviço '{nome_servico}' demorou para responder.",
                "servico": nome_servico,
                "request_id": req_id,
            },
        )
    except httpx.RequestError:
        return JSONResponse(
            status_code=503,
            content={
                "detail": f"Serviço '{nome_servico}' indisponível no momento.",
                "servico": nome_servico,
                "request_id": req_id,
            },
        )

    headers_saida: dict[str, str] = {}
    for chave in ("content-type", "cache-control", "www-authenticate"):
        valor = resp.headers.get(chave)
        if valor:
            headers_saida[chave] = valor

    return Response(content=resp.content, status_code=resp.status_code, headers=headers_saida)


async def _checar_servico(cliente: httpx.AsyncClient, nome: str, base_url: str) -> tuple[str, dict]:
    inicio = time.perf_counter()
    try:
        resp = await cliente.get(
            f"{base_url}/saude",
            headers={"X-Request-ID": request_id_ctx.get()},
            timeout=config.SAUDE_TIMEOUT_SEGUNDOS,
        )
        latencia_ms = round((time.perf_counter() - inicio) * 1000, 1)
        dados = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code == 200 and dados.get("status") == "ok":
            return nome, {"status": "ok", "latencia_ms": latencia_ms, **dados}
        return nome, {"status": "degradado", "codigo": resp.status_code, "latencia_ms": latencia_ms, **dados}
    except Exception as exc:
        latencia_ms = round((time.perf_counter() - inicio) * 1000, 1)
        return nome, {"status": "offline", "latencia_ms": latencia_ms, "erro": type(exc).__name__}


async def saude_agregada() -> dict:
    cliente = obter_cliente_http()
    destinos = servicos_destinos()
    resultados = await asyncio.gather(
        *(_checar_servico(cliente, nome, url) for nome, url in destinos.items())
    )
    servicos = dict(resultados)
    todos_ok = all(info.get("status") == "ok" for info in servicos.values())
    return {
        "status": "ok" if todos_ok else "degradado",
        "gateway": "ok",
        "servicos": servicos,
    }

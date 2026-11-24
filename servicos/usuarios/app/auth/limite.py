"""Limite de tentativas de login com suporte distribuído via Redis e fallback em memória."""
import hashlib
import logging
import time
from collections import defaultdict
from threading import Lock

import redis

from app.config import LOGIN_JANELA_SEGUNDOS, LOGIN_MAX_FALHAS, REDIS_URL

log = logging.getLogger("helpdesk.usuarios")

_falhas: dict[str, list[float]] = defaultdict(list)
_trava = Lock()
_cliente_redis: redis.Redis | None = None
_redis_url_atual = ""


def _obter_redis() -> redis.Redis | None:
    global _cliente_redis, _redis_url_atual
    url = REDIS_URL
    if not url:
        return None
    if _cliente_redis is None or _redis_url_atual != url:
        _cliente_redis = redis.Redis.from_url(
            url, decode_responses=True, socket_timeout=0.5, socket_connect_timeout=0.5
        )
        _redis_url_atual = url
    return _cliente_redis


def _chave_redis(chave: str) -> str:
    # Armazena hash SHA-256 em vez do e-mail bruto para evitar PII nas chaves do Redis
    digest = hashlib.sha256(chave.encode("utf-8")).hexdigest()
    return f"helpdesk:login_falhas:{digest}"


def _recentes(chave: str, agora: float) -> list[float]:
    _falhas[chave] = [t for t in _falhas[chave] if agora - t < LOGIN_JANELA_SEGUNDOS]
    return _falhas[chave]


def bloqueado(chave: str) -> bool:
    cliente = _obter_redis()
    if cliente is not None:
        try:
            valor = cliente.get(_chave_redis(chave))
            if valor is not None:
                return int(valor) >= LOGIN_MAX_FALHAS
        except redis.RedisError as exc:
            log.warning("Redis indisponível ao verificar limite de login; usando memória: %s", exc)
    with _trava:
        return len(_recentes(chave, time.monotonic())) >= LOGIN_MAX_FALHAS


def registrar_falha(chave: str) -> None:
    cliente = _obter_redis()
    if cliente is not None:
        try:
            k = _chave_redis(chave)
            pipe = cliente.pipeline()
            pipe.incr(k)
            pipe.expire(k, LOGIN_JANELA_SEGUNDOS, nx=True)
            pipe.execute()
            return
        except redis.RedisError as exc:
            log.warning("Redis indisponível ao registrar falha de login; usando memória: %s", exc)
    with _trava:
        agora = time.monotonic()
        _recentes(chave, agora).append(agora)


def limpar(chave: str) -> None:
    cliente = _obter_redis()
    if cliente is not None:
        try:
            cliente.delete(_chave_redis(chave))
        except redis.RedisError as exc:
            log.warning("Redis indisponível ao limpar limite de login: %s", exc)
    with _trava:
        _falhas.pop(chave, None)


def limpar_tudo() -> None:
    with _trava:
        _falhas.clear()


def status_armazenamento() -> str:
    cliente = _obter_redis()
    if cliente is None:
        return "memoria"
    try:
        cliente.ping()
        return "redis"
    except redis.RedisError:
        return "memoria_fallback"
